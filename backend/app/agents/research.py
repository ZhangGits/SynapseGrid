"""研究 Agent — 任务拆解与分析要点生成

负责：
1. 接收用户 prompt，根据模板拆解为多个分析维度
2. 调用 LLM 生成带 <finding> 标签的 Markdown 叙述
3. 从 Markdown 中解析出结构化 findings
4. 提供 rebuild() 方法在回退时重新组织叙述

v4.0 Phase 1 更新：
- run() 返回类型从 list[dict] 改为 tuple[str, list[dict]]
- 新增 FINDINGS_MARKDOWN_PROMPT：要求 LLM 输出带 <finding> 标签的 Markdown
- 新增 parse_finding_tags() 解析器
- 新增 rebuild() 方法用于回退后重新叙述
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from app.schemas.machine_wire import LlmConfig
from app.services.llm_client import LLMEngine, call_llm, estimate_cost
from app.services.template_engine import render_template

logger = logging.getLogger(__name__)

# ── v4.0 Phase 1: 要求 LLM 输出带 <finding> 标签的 Markdown ──
FINDINGS_MARKDOWN_PROMPT = """你是一个专业的分析助手。请根据用户的问题和指定的分析维度，撰写一份带分析要点标记的报告。

格式要求：
每个分析要点用 <finding id="f1" confidence="0.85">...</finding> 标签包裹。
标签外是自然的过渡叙述，标签内是具体的分析要点内容。

要求：
1. 每个分析要点必须有一个唯一的 id（f1, f2, f3...）
2. confidence 是 0-1 之间的浮点数，表示置信度
3. 在标签内撰写完整的分析要点（观点 + 论据）
4. 标签之间用自然的过渡叙述连接
5. 生成 3-5 个分析要点
6. 整体报告用 Markdown 格式组织（标题、段落等）"""

# 用于 rebuild 的系统提示词
REBUILD_PROMPT = """你是一个专业的分析报告修订专家。用户回退了一个分析要点，请你基于剩余的有效要点重新组织报告。

要求：
1. 保持 <finding> 标签格式不变，只保留剩余的有效 finding
2. 移除与被回退要点相关的段落和论述
3. 保持剩余要点之间的逻辑连贯性
4. 在报告顶部加入回退通知
5. 不要重新生成新的 finding，只使用现有的剩余 findings
6. 整体报告仍用 Markdown 格式组织"""


class ResearchAgent:
    """研究 Agent：将用户问题拆解为多个分析要点"""

    def __init__(self) -> None:
        self._mock_mode = False

    async def run(self, prompt: str, llm: LlmConfig, template: str = "general",
                  conversation_history: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        """执行研究阶段，返回 (raw_markdown, findings)"""
        logger.info("ResearchAgent.run  prompt_len=%s  template=%s  model=%s",
                     len(prompt), template, llm.model)
        if not llm.api_key:
            self._mock_mode = True
            logger.warning("No API key -- using deterministic mock output")
            return self._mock_findings(prompt, template)
        self._mock_mode = False
        try:
            return await self._llm_findings(prompt, llm, template, conversation_history)
        except Exception:
            logger.exception("LLM call failed, falling back to mock output")
            return self._mock_findings(prompt, template)

    async def _llm_findings(self, prompt, llm, template, conversation_history):
        """调用 LLM 生成带 <finding> 标签的 Markdown"""
        messages = [{"role": "system", "content": FINDINGS_MARKDOWN_PROMPT}]
        tc = render_template(template, prompt)
        messages.append({"role": "user", "content": tc if tc else prompt})
        config = LLMEngine.build_config(api_key=llm.api_key, model=llm.model, base_url=llm.base_url)
        result = await call_llm(config, messages, temperature=0.7, max_tokens=4096)
        content = result["content"]
        raw_markdown, findings = self.parse_finding_tags(content, llm)
        cost = estimate_cost(llm.model, result["tokens_input"], result["tokens_output"])
        pc = round(cost / max(len(findings), 1), 6)
        for f in findings:
            f["cost_usd"] = pc
        logger.info("ResearchAgent: LLM OK  findings=%s", len(findings))
        return raw_markdown, findings

    def parse_finding_tags(self, raw_text: str, llm: LlmConfig | None = None):
        """从 LLM 输出中解析 <finding> 标签"""
        pattern = r'<finding\s+id="([^"]+)"\s+confidence="([^"]+)"\s*>(.*?)</finding>'
        matches = re.findall(pattern, raw_text, re.DOTALL)
        provider = llm.provider if llm else "unknown"
        model_name = llm.model if llm else "unknown"
        if not matches:
            logger.warning("No <finding> tags found, trying JSON fallback")
            findings_data = None
            try:
                findings_data = json.loads(raw_text)
            except (json.JSONDecodeError, ValueError):
                m2 = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
                if m2:
                    try:
                        findings_data = json.loads(m2.group(1))
                    except (json.JSONDecodeError, ValueError):
                        pass
            if findings_data is None or not isinstance(findings_data, list):
                logger.error("Cannot parse LLM output")
                return raw_text, []
            findings = []
            for i, item in enumerate(findings_data):
                findings.append({
                    "id": item.get("id", f"f{i+1}"),
                    "claim": item.get("claim", ""),
                    "evidence": item.get("evidence", ""),
                    "source": f"Research Agent ({provider})",
                    "confidence": float(item.get("confidence", 0.7)),
                    "agent": "research",
                    "model": model_name,
                    "cost_usd": 0.0,
                })
            return raw_text, findings
        findings = []
        for fid, conf_str, content in matches:
            claim = content.strip()
            findings.append({
                "id": fid,
                "claim": claim[:200],
                "evidence": claim,
                "source": f"Research Agent ({provider})",
                "confidence": float(conf_str),
                "agent": "research",
                "model": model_name,
                "cost_usd": 0.0,
            })
        logger.info("Parsed %d findings from tags", len(findings))
        return raw_text, findings

    async def rebuild(self, original_markdown: str, rolled_back_id: str,
                       reason: str, remaining_findings: list[dict[str, Any]],
                       llm: LlmConfig) -> str:
        """基于剩余 findings 重新组织 Markdown 叙述"""
        logger.info("ResearchAgent.rebuild  rolled_back=%s  remaining=%s",
                     rolled_back_id, len(remaining_findings))
        if not llm.api_key:
            return self._text_rebuild(original_markdown, rolled_back_id, reason, remaining_findings)
        try:
            return await self._llm_rebuild(original_markdown, rolled_back_id, reason,
                                            remaining_findings, llm)
        except Exception:
            logger.exception("LLM rebuild failed, using text-based rebuild")
            return self._text_rebuild(original_markdown, rolled_back_id, reason, remaining_findings)

    async def _llm_rebuild(self, original_markdown, rolled_back_id, reason,
                            remaining_findings, llm):
        """使用 LLM 重新组织 Markdown"""
        rs = "\n".join(f"- {f['id']}: {f.get('claim', f.get('evidence', ''))[:120]}"
                       for f in remaining_findings)
        sp = REBUILD_PROMPT.format(rolled_back_id=rolled_back_id, reason=reason)
        up = (f"## Original Report\n\n{original_markdown}\n\n"
              f"## Remaining Findings\n\n{rs}\n\n"
              f"## Rolled Back\n\n- {rolled_back_id}: {reason}\n\n"
              f"Please regenerate the report.")
        config = LLMEngine.build_config(api_key=llm.api_key, model=llm.model, base_url=llm.base_url)
        result = await call_llm(config, [
            {"role": "system", "content": sp},
            {"role": "user", "content": up}], temperature=0.5, max_tokens=4096)
        return result["content"]

    def _text_rebuild(self, original_markdown, rolled_back_id, reason, remaining_findings):
        """纯文本方式重建 Markdown（不需要 LLM）"""
        pattern = rf'<finding\s+id="{re.escape(rolled_back_id)}"[^>]*>.*?</finding>'
        cleaned = re.sub(pattern, "", original_markdown, flags=re.DOTALL)
        rn = (f"\n\n> **Rollback Notice**\n"
              f"> Finding `{rolled_back_id}` has been rolled back because: {reason}\n")
        if remaining_findings:
            rt = "\n".join(f"- **{f['id']}** ({f.get('confidence', 0):.0%}): {f.get('claim', '')[:80]}..."
                           for f in remaining_findings)
            rn += (f"\n> **Remaining active findings** ({len(remaining_findings)}):\n{rt}\n")
        return rn + "\n" + cleaned.strip()

    def _mock_findings(self, prompt, template):
        """生成确定性 mock 分析要点和 Markdown"""
        if template == "finance":
            findings = [
                {"id": "f1", "claim": f"Finance: {prompt[:50]}... growth trend",
                 "evidence": f"According to Q3 report, {prompt[:50]} showed 12% revenue growth and 45% gross margin.",
                 "source": "Research Agent (mock)", "confidence": 0.85, "agent": "research_01", "model": "mock", "cost_usd": 0.001},
                {"id": "f2", "claim": "Market risk under control, liquidity needs monitoring",
                 "evidence": "VIX at 18.5 (median). LCR at 135% (>100%). Cash ratio declined from 0.45 to 0.38.",
                 "source": "Research Agent (mock)", "confidence": 0.72, "agent": "research_01", "model": "mock", "cost_usd": 0.001},
                {"id": "f3", "claim": "Add hedging for FX risk",
                 "evidence": "DXY 3-month volatility 8.2%. USD/CNY implied vol 6.5%. Recommend 30% hedge.",
                 "source": "Research Agent (mock)", "confidence": 0.68, "agent": "research_01", "model": "mock", "cost_usd": 0.001},
            ]
            e1, e2, e3 = findings[0]["evidence"], findings[1]["evidence"], findings[2]["evidence"]
            rm = (f"# Financial Analysis\n\n## Overview\n\nAnalysis of \"{prompt[:30]}\".\n\n"
                  f"## Findings\n\n<finding id=\"f1\" confidence=\"0.85\">{e1}</finding>\n\n"
                  f"Beyond financial metrics, risk factors deserve attention.\n\n"
                  f"<finding id=\"f2\" confidence=\"0.72\">{e2}</finding>\n\n"
                  f"Based on above, we recommend:\n\n"
                  f"<finding id=\"f3\" confidence=\"0.68\">{e3}</finding>\n\n"
                  f"## Conclusion\n\nMaintain current strategy, add hedging.")
        elif template == "legal":
            findings = [
                {"id": "f1", "claim": f"Legal: {prompt[:50]}... contract interpretation",
                 "evidence": f"Under Contract Law Art 125, terms shall be interpreted by wording, context, purpose, customs and good faith. {prompt[:50]} contains ambiguity.",
                 "source": "Research Agent (mock)", "confidence": 0.82, "agent": "research_01", "model": "mock", "cost_usd": 0.001},
                {"id": "f2", "claim": "Precedents favor protecting the weaker party",
                 "evidence": "In (2024) SPC Civil Final 123, court held that boilerplate terms without adequate notice are not part of contract. Relevant here.",
                 "source": "Research Agent (mock)", "confidence": 0.75, "agent": "research_01", "model": "mock", "cost_usd": 0.001},
            ]
            e1, e2 = findings[0]["evidence"], findings[1]["evidence"]
            rm = (f"# Legal Analysis\n\n## Overview\n\nAnalysis of \"{prompt[:30]}\".\n\n"
                  f"## Findings\n\n<finding id=\"f1\" confidence=\"0.82\">{e1}</finding>\n\n"
                  f"Precedents also relevant.\n\n<finding id=\"f2\" confidence=\"0.75\">{e2}</finding>\n\n"
                  f"## Conclusion\n\nAdopt cautious approach.")
        else:
            findings = [
                {"id": "f1", "claim": f"Finding 1: {prompt[:50]}... tech maturity and demand",
                 "evidence": f"Tech maturity: {prompt[:50]}... reached TRL 7-8. Demand: Gartner predicts 25% CAGR over 3 years.",
                 "source": "Research Agent (mock)", "confidence": 0.88, "agent": "research_01", "model": "mock", "cost_usd": 0.001},
                {"id": "f2", "claim": f"Finding 2: {prompt[:50]}... accelerating trend",
                 "evidence": f"R&D investment +35% YoY, patents +40%. Leading firms expanding market share.",
                 "source": "Research Agent (mock)", "confidence": 0.76, "agent": "research_01", "model": "mock", "cost_usd": 0.001},
                {"id": "f3", "claim": f"Finding 3: {prompt[:50]}... standardization and regulation challenges",
                 "evidence": f"No unified standards exist. Regulatory compliance costs 15-20% of total costs.",
                 "source": "Research Agent (mock)", "confidence": 0.71, "agent": "research_01", "model": "mock", "cost_usd": 0.001},
            ]
            e1, e2, e3 = findings[0]["evidence"], findings[1]["evidence"], findings[2]["evidence"]
            rm = (f"# Analysis Report\n\n## Overview\n\nAnalysis of \"{prompt[:30]}\".\n\n"
                  f"## Findings\n\n<finding id=\"f1\" confidence=\"0.88\">{e1}</finding>\n\n"
                  f"Further observations:\n\n<finding id=\"f2\" confidence=\"0.76\">{e2}</finding>\n\n"
                  f"Challenges remain:\n\n<finding id=\"f3\" confidence=\"0.71\">{e3}</finding>\n\n"
                  f"## Conclusion\n\nOutlook positive but watch standardization and regulation.")
        return rm, findings
