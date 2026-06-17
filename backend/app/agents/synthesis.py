"""综合 Agent — LogicGraph 论证结构提取器 + 节点摘要生成器

负责：
1. 从 Research 生成的 raw_markdown 和 Verification 的 assessments/relations 中提取论证结构
2. 调用 LLM 提取 LogicGraph（question/conclusion/claim/evidence 节点 + supports/tension 边）
3. 为每个节点生成 1-2 句简洁摘要（用于前端画布显示）
4. 返回 SynthesisResult（logic_graph + enriched_markdown + node_map）

v4.0 Phase 1 更新：
- 不再生成仪表盘 CanvasSchema，改为提取 LogicGraph 论证结构
- run() 签名改为 (raw_markdown, findings, assessments, relations, llm, template)
- 返回 SynthesisResult 而非 dict
- 删除 _build_canvas_schema() 方法

v4.0 摘要特性更新：
- 新增 _generate_node_summaries() 方法，对每个节点提取 1-2 句摘要
- LogicNode 新增 summary 字段，前端画布优先显示摘要而非完整 label
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.schemas.machine_wire import (
    CredibilityAssessment,
    FindingRelation,
    LlmConfig,
    LogicEdge,
    LogicGraph,
    LogicNode,
    SynthesisResult,
)
from app.services.llm_client import LLMEngine, call_llm

logger = logging.getLogger(__name__)

# 节点摘要提取提示词
NODE_SUMMARY_SYSTEM_PROMPT = """你是一个专业的文本摘要专家。请为以下论证结构中的每个节点生成一句简洁的摘要（不超过30个中文字符或60个英文字符）。

对于每种节点类型：
- question: 用问句形式概括核心问题
- conclusion: 概括最终结论（15字以内）
- claim: 概括主张的核心观点（20字以内）
- evidence: 概括证据的关键信息（20字以内）

请严格按照以下 JSON 格式返回（只返回 JSON，不要包含 markdown 代码块标记）：
{
  "summaries": {
    "node_id_1": "摘要文本1",
    "node_id_2": "摘要文本2",
    ...
  }
}"""

# LogicGraph 提取提示词（v2.0：合并节点摘要生成）
LOGIC_GRAPH_SYSTEM_PROMPT = """你是一个专业的论证结构分析专家。请根据以下分析报告和可信度评估结果，提取论证结构图，并为每个节点生成简洁摘要。

## 节点类型
- question: 核心问题
- conclusion: 综合结论
- claim: 分析主张（对应 findings）
- evidence: 支持证据

## 边类型
- supports: 支持关系（A 支持 B）
- perspective_difference: 视角差异（观察维度不同，各自可信）
- tension: 张力（存在不一致但可调和）
- genuine_contradiction: 真实矛盾（逻辑不可调和）

## 输出格式

请严格按照以下 JSON 格式返回（不要包含 markdown 代码块标记）：

{
  "nodes": [
    {"id": "q1", "type": "question", "label": "核心问题描述", "summary": "核心问题摘要", "finding_id": null, "importance": 0.9},
    {"id": "n1", "type": "claim", "label": "主张描述", "summary": "主张摘要", "finding_id": "f1", "credibility": 0.86, "importance": 0.8},
    {"id": "n2", "type": "evidence", "label": "证据描述", "summary": "证据摘要", "finding_id": null, "credibility": 0.5, "importance": 0.5},
    {"id": "c1", "type": "conclusion", "label": "结论描述", "summary": "结论摘要", "finding_id": null, "importance": 0.9}
  ],
  "edges": [
    {"from_id": "n1", "to_id": "c1", "type": "supports", "description": "支持结论"},
    {"from_id": "n2", "to_id": "n1", "type": "supports", "description": "提供证据"}
  ]
}

## 摘要要求

为每个节点生成 `summary` 字段：
- question: 问句形式概括核心问题（不超过20字）
- conclusion: 概括最终结论（不超过15字）
- claim: 概括主张核心观点（不超过20字）
- evidence: 概括证据关键信息（不超过20字）

## 要求

1. 每个 finding 至少对应一个 claim 节点
2. 结论节点应综合所有主张
3. 边要反映真实的逻辑关系
4. credibility 从评估结果中获取，默认为 0.5
5. 只返回 JSON 对象"""


class SynthesisAgent:
    """综合 Agent：从报告和评估中提取论证结构图 + 为节点生成摘要

    v4.0 Phase 1：LogicGraph 提取器。
    不再生成仪表盘，改为提取论证结构供前端 Canvas 渲染。

    v4.0 摘要特性：为每个节点生成简洁摘要，前端画布上显示摘要而非完整 label。
    """

    def __init__(self) -> None:
        self._mock_mode = False

    async def run(
        self,
        raw_markdown: str,
        findings: list[dict[str, Any]],
        assessments: list[CredibilityAssessment] | list[dict],
        relations: list[FindingRelation] | list[dict],
        llm: LlmConfig,
        template: str = "general",
    ) -> SynthesisResult:
        """执行论证结构提取 + 节点摘要生成

        Args:
            raw_markdown: Research 生成的原始 Markdown
            findings: 分析要点列表
            assessments: 可信度评估列表
            relations: finding 间关系列表
            llm: LLM 配置
            template: 场景模板

        Returns:
            SynthesisResult（logic_graph + enriched_markdown + node_map）
        """
        logger.info("SynthesisAgent.run  findings=%s  assessments=%s  relations=%s  template=%s",
                     len(findings), len(assessments), len(relations), template)

        if not llm.api_key:
            self._mock_mode = True
            logger.warning("No API key — using mock LogicGraph")
            return self._mock_synthesis(raw_markdown, findings, assessments, relations, template)

        self._mock_mode = False
        try:
            return await self._llm_extract(raw_markdown, findings, assessments, relations, llm, template)
        except Exception:
            logger.exception("LLM LogicGraph extraction failed, falling back to mock")
            return self._mock_synthesis(raw_markdown, findings, assessments, relations, template)

    async def _generate_node_summaries(
        self,
        nodes: list[LogicNode],
        raw_markdown: str,
        llm: LlmConfig,
    ) -> None:
        """调用 LLM 为每个论证节点生成简洁摘要

        结果直接写入每个 LogicNode 的 summary 字段（原地修改）。

        Args:
            nodes: 论证节点列表（会原地修改 summary 字段）
            raw_markdown: 原始报告 Markdown
            llm: LLM 配置
        """
        if not nodes:
            return

        # 构建节点描述文本块
        node_descriptions = ""
        for n in nodes:
            node_descriptions += f"- {n.id} (type={n.type}): {n.label[:200]}\n"

        user_prompt = (
            f"## 原始报告上下文\n\n{raw_markdown[:1200]}\n\n"
            f"## 需要生成摘要的节点\n\n{node_descriptions}\n\n"
            f"请为以上每个节点生成一句简洁摘要。"
        )

        config = LLMEngine.build_config(
            api_key=llm.api_key,
            model=llm.model,
            base_url=llm.base_url,
        )
        result = await call_llm(config, [
            {"role": "system", "content": NODE_SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ], temperature=0.2, max_tokens=2048)

        content = result["content"]
        summaries_data: dict[str, Any] | None = None

        try:
            summaries_data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            # 尝试从 markdown 代码块中提取
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if json_match:
                try:
                    summaries_data = json.loads(json_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    pass

        if not summaries_data:
            logger.warning("Failed to parse node summaries JSON from LLM response")
            return

        summaries: dict[str, str] = summaries_data.get("summaries", {})
        for n in nodes:
            if n.id in summaries and summaries[n.id]:
                n.summary = summaries[n.id]

        logger.info("Generated summaries for %d/%d nodes", len(summaries), len(nodes))

    def _generate_local_summaries(self, nodes: list[LogicNode]) -> None:
        """本地规则生成摘要（fallback：当 LLM 不可用时使用）

        使用启发式规则从 label 中截取摘要：
        - 中文按句号/逗号截断
        - 英文按句号/逗号截断
        - 最多保留 40 个字符

        Args:
            nodes: 论证节点列表（会原地修改 summary 字段）
        """
        for n in nodes:
            if n.summary:
                continue  # 已有摘要，跳过
            text = n.label
            if len(text) <= 40:
                n.summary = text
                continue

            # 查找断句位置（中文和英文标点）
            best_cut = 40
            for i in range(40, max(15, 40 - 25), -1):
                if i < len(text) and text[i] in '。！？.!?;；，,':
                    best_cut = i + 1
                    break
            cut = text[:best_cut].strip()
            n.summary = cut + "..." if cut and len(cut) < len(text) else cut

    async def _llm_extract(
        self,
        raw_markdown: str,
        findings: list[dict[str, Any]],
        assessments: list[CredibilityAssessment] | list[dict],
        relations: list[FindingRelation] | list[dict],
        llm: LlmConfig,
        template: str,
    ) -> SynthesisResult:
        """调用 LLM 提取 LogicGraph + 生成节点摘要"""
        # 构建 credibility map
        cred_map: dict[str, float] = {}
        for a in assessments:
            if isinstance(a, CredibilityAssessment):
                cred_map[a.finding_id] = a.overall_credibility
            elif isinstance(a, dict):
                cred_map[a.get("finding_id", "")] = a.get("overall_credibility", 0.5)

        # 构建 findings 摘要
        findings_text = ""
        for f in findings:
            fid = f.get("id", "")
            cred = cred_map.get(fid, f.get("confidence", 0.5))
            findings_text += f"- {fid} ({cred:.0%}): {f.get('claim', '')[:150]}\n"

        # 构建 relations 摘要
        rel_text = ""
        for r in relations:
            if isinstance(r, FindingRelation):
                rel_text += f"- {r.relation_type}: {', '.join(r.between)} — {r.description}\n"
            elif isinstance(r, dict):
                rel_text += f"- {r.get('relation_type', '?')}: {', '.join(r.get('between', []))} — {r.get('description', '')}\n"

        user_prompt = (
            f"## 分析报告摘要\n\n{raw_markdown[:2000]}\n\n"
            f"## 分析要点及可信度\n\n{findings_text}\n"
            f"## 要点间关系\n\n{rel_text}\n\n"
            f"请提取上述报告的论证结构图。"
        )

        config = LLMEngine.build_config(api_key=llm.api_key, model=llm.model, base_url=llm.base_url)
        result = await call_llm(config, [
            {"role": "system", "content": LOGIC_GRAPH_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ], temperature=0.3, max_tokens=4096)

        content = result["content"]
        try:
            graph_data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if json_match:
                graph_data = json.loads(json_match.group(1))
            else:
                raise

        # 构建 LogicGraph（v2.0：从LLM返回中直接提取summary）
        nodes: list[LogicNode] = []
        for n in graph_data.get("nodes", []):
            nodes.append(LogicNode(
                id=n.get("id", ""),
                type=n.get("type", "claim"),
                label=n.get("label", ""),
                summary=n.get("summary"),  # ← 直接从LLM获取摘要
                finding_id=n.get("finding_id"),
                credibility=float(n.get("credibility", 0.5)),
                rolled_back=n.get("rolled_back", False),
                importance=float(n.get("importance", 0.5)),
            ))

        edges: list[LogicEdge] = []
        for e in graph_data.get("edges", []):
            edges.append(LogicEdge(
                from_id=e.get("from_id", ""),
                to_id=e.get("to_id", ""),
                type=e.get("type", "supports"),
                description=e.get("description"),
            ))

        # 对未生成摘要的节点使用本地 fallback（不再需要第二次LLM调用）
        self._generate_local_summaries(nodes)

        logic_graph = LogicGraph(nodes=nodes, edges=edges)

        # 构建 node_map（节点 ID → finding ID 映射）
        node_map: dict[str, str] = {}
        for n in nodes:
            if n.finding_id:
                node_map[n.id] = n.finding_id

        logger.info("SynthesisAgent: LogicGraph extracted  nodes=%s  edges=%s  summaries=%s",
                     len(nodes), len(edges),
                     sum(1 for n in nodes if n.summary))
        return SynthesisResult(
            logic_graph=logic_graph,
            enriched_markdown=raw_markdown,
            node_map=node_map,
        )

    def _mock_synthesis(
        self,
        raw_markdown: str,
        findings: list[dict[str, Any]],
        assessments: list[CredibilityAssessment] | list[dict],
        relations: list[FindingRelation] | list[dict],
        template: str,
    ) -> SynthesisResult:
        """生成 mock LogicGraph（用于开发和测试）"""
        cred_map: dict[str, float] = {}
        for a in assessments:
            if isinstance(a, CredibilityAssessment):
                cred_map[a.finding_id] = a.overall_credibility
            elif isinstance(a, dict):
                cred_map[a.get("finding_id", "")] = a.get("overall_credibility", 0.5)

        # 构建节点
        nodes: list[LogicNode] = [
            LogicNode(
                id="q1",
                type="question",
                label=f"分析：{template} 主题",
                summary=f"核心问题：{template}主题分析",
                importance=0.9,
            ),
        ]

        for f in findings:
            fid = f.get("id", "")
            cred = cred_map.get(fid, f.get("confidence", 0.7))
            claim_text = f.get("claim", "")[:100]
            nodes.append(LogicNode(
                id=f"n_{fid}",
                type="claim",
                label=claim_text,
                summary=claim_text[:40] + ("..." if len(claim_text) > 40 else ""),
                finding_id=fid,
                credibility=cred,
                importance=0.7,
            ))
            # 每个 claim 配一个 evidence 节点
            evidence = f.get("evidence", f.get("claim", ""))
            evidence_text = evidence[:100] if isinstance(evidence, str) else str(evidence)[:100]
            nodes.append(LogicNode(
                id=f"e_{fid}",
                type="evidence",
                label=evidence_text,
                summary=evidence_text[:40] + ("..." if len(evidence_text) > 40 else ""),
                finding_id=fid,
                credibility=cred,
                importance=0.4,
            ))

        nodes.append(LogicNode(
            id="c1",
            type="conclusion",
            label="综合结论",
            summary="综合各主张得出的最终结论",
            importance=0.9,
        ))

        # 构建边：evidence → claim → conclusion
        edges: list[LogicEdge] = []
        for f in findings:
            fid = f.get("id", "")
            edges.append(LogicEdge(
                from_id=f"e_{fid}",
                to_id=f"n_{fid}",
                type="supports",
                description="提供证据",
            ))
            edges.append(LogicEdge(
                from_id=f"n_{fid}",
                to_id="c1",
                type="supports",
                description="支持结论",
            ))

        # 从 relations 添加关系边
        for r in relations:
            if isinstance(r, FindingRelation):
                between = r.between
                rt = r.relation_type
                desc = r.description
            elif isinstance(r, dict):
                between = r.get("between", [])
                rt = r.get("relation_type", "perspective_difference")
                desc = r.get("description", "")
            else:
                continue
            if len(between) >= 2:
                edges.append(LogicEdge(
                    from_id=f"n_{between[0]}",
                    to_id=f"n_{between[1]}",
                    type=rt,
                    description=desc,
                ))

        logic_graph = LogicGraph(nodes=nodes, edges=edges)
        node_map: dict[str, str] = {}
        for n in nodes:
            if n.finding_id:
                node_map[n.id] = n.finding_id

        logger.info("Mock LogicGraph generated  nodes=%s  edges=%s", len(nodes), len(edges))
        return SynthesisResult(
            logic_graph=logic_graph,
            enriched_markdown=raw_markdown,
            node_map=node_map,
        )