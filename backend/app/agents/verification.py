"""验证 Agent — 可信度评估

负责：
1. 对 Research Agent 生成的每个 finding 进行独立的四维度可信度评估
2. 检测 findings 之间的关系（视角差异/张力/真实矛盾）
3. 返回 CredibilityAssessment 列表和 FindingRelation 列表

设计理念（v4.0）：
- 不再"检测矛盾并标记无效"——矛盾可能只是视角差异
- 每个 finding 独立评估，不因存在不一致而降低评分
- 区分 perspective_difference（视角差异）、tension（张力）、genuine_contradiction（真实矛盾）
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.schemas.machine_wire import (
    CredibilityAssessment,
    FindingRelation,
    LlmConfig,
)
from app.services.llm_client import LLMEngine, call_llm

logger = logging.getLogger(__name__)

# 可信度评估系统提示词
CREDIBILITY_SYSTEM_PROMPT = """你是一个分析要点可信度评估专家。请对以下 TOON 格式的分析要点进行独立的四维度可信度评估，并检测它们之间的关系。

TOON 格式说明：每行一个 finding，格式为 @id|置信度|观点摘要

## 评估维度（每个维度 0-1 分）

1. **evidence_strength**（证据强度）：论据是否具体、充分、可验证
2. **source_reliability**（来源可靠性）：分析来源是否可信、权威
3. **reasoning_soundness**（推理合理性）：从证据到结论的推理是否严密
4. **data_consistency**（数据一致性）：数据是否自洽、与其他 finding 一致

## 关系类型

- **perspective_difference**：视角差异——观察维度不同导致不同结论，各自可信（不是错误）
- **tension**：张力——存在不一致，但可以通过进一步分析调和
- **genuine_contradiction**：真实矛盾——逻辑上不可调和的对立

## 输出格式

请严格按照以下 JSON 格式返回（不要包含 markdown 代码块标记）：

{
  "assessments": [
    {
      "finding_id": "f1",
      "evidence_strength": 0.85,
      "source_reliability": 0.80,
      "reasoning_soundness": 0.90,
      "data_consistency": 0.88,
      "overall_credibility": 0.86,
      "assessment": "论据充分，推理严密，来源可靠",
      "concerns": ["数据来源可能过时"],
      "suggestions": ["建议补充最新数据"]
    }
  ],
  "relations": [
    {
      "between": ["f1", "f2"],
      "relation_type": "perspective_difference",
      "description": "f1 从长期技术角度分析，f2 从短期市场角度分析，观察维度不同"
    }
  ]
}

## 要求

1. 每个 finding 生成一个独立的 assessment，评分客观
2. overall_credibility = (evidence_strength * 0.3 + source_reliability * 0.2 + reasoning_soundness * 0.3 + data_consistency * 0.2)
3. perspective_difference 不应被视为问题，它反映了多维度分析的完整性
4. 只返回 JSON 对象，不要包含其他文字"""


class VerificationAgent:
    """验证 Agent：可信度评估

    对 Research Agent 生成的 findings 进行四维度可信度评估，
    检测 findings 之间的关系（视角差异/张力/真实矛盾）。
    """

    def __init__(self) -> None:
        self._mock_mode = False

    async def run(
        self,
        findings: list[dict[str, Any]],
        llm: LlmConfig,
        template: str = "general",
    ) -> tuple[list[CredibilityAssessment], list[FindingRelation]]:
        """执行可信度评估

        对每个 finding 独立评估四维度可信度，检测 finding 间关系。

        Args:
            findings: Research Agent 生成的分析要点列表
            llm: LLM 配置
            template: 场景模板

        Returns:
            (assessments, relations) 元组：
            - assessments: 可信度评估列表
            - relations: finding 间关系列表
        """
        logger.info(
            "VerificationAgent.run  findings=%s  template=%s  model=%s",
            len(findings), template, llm.model,
        )

        if not llm.api_key:
            self._mock_mode = True
            logger.warning("No API key — using deterministic mock output")
            return self._mock_assess(findings, template)

        self._mock_mode = False
        try:
            config = LLMEngine.build_config(api_key=llm.api_key, model=llm.model, base_url=llm.base_url)
            return await self._llm_assess(findings, config, template)
        except Exception as e:
            logger.exception("LLM credibility assessment failed, falling back to mock")
            return self._mock_assess(findings, template)

    async def _llm_assess(
        self,
        findings: list[dict[str, Any]],
        llm: LlmConfig,
        template: str,
    ) -> tuple[list[CredibilityAssessment], list[FindingRelation]]:
        """调用 LLM 进行可信度评估

        Args:
            findings: 分析要点列表
            llm: LLM 配置
            template: 场景模板

        Returns:
            (assessments, relations) 元组

        Raises:
            json.JSONDecodeError: LLM 返回的 JSON 解析失败时抛出
            httpx.HTTPError: API 调用失败时抛出
        """
        # 构建 TOON 格式 findings（v2.0：增加evidence和source，控制在200字/finding）
        toon_lines = []
        for f in findings:
            fid = f.get("id", "")
            conf = f.get("confidence", 0)
            claim = f.get("claim", "")[:80]
            evidence = f.get("evidence", "")[:80]
            source = f.get("source", "")[:40]
            parts = [f"@{fid}|{conf:.0%}|claim={claim}"]
            if evidence and evidence != claim:
                parts.append(f"evidence={evidence}")
            if source:
                parts.append(f"source={source}")
            toon_lines.append("|".join(parts))
        findings_toon = "\n".join(toon_lines)

        messages = [
            {"role": "system", "content": CREDIBILITY_SYSTEM_PROMPT},
            {"role": "user", "content": f"请评估以下分析要点的可信度：\n\n{findings_toon}"},
        ]

        result = await call_llm(llm, messages, temperature=0.3, max_tokens=4096)
        content = result["content"]

        # 解析 JSON 响应
        try:
            verify_data = json.loads(content)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
            if json_match:
                verify_data = json.loads(json_match.group(1))
            else:
                raise

        # 解析 assessments
        assessments = []
        assessment_items = verify_data.get("assessments", [])
        for item in assessment_items:
            assessments.append(CredibilityAssessment(
                finding_id=item.get("finding_id", ""),
                evidence_strength=float(item.get("evidence_strength", 0.5)),
                source_reliability=float(item.get("source_reliability", 0.5)),
                reasoning_soundness=float(item.get("reasoning_soundness", 0.5)),
                data_consistency=float(item.get("data_consistency", 0.5)),
                overall_credibility=float(item.get("overall_credibility", 0.5)),
                assessment=item.get("assessment", ""),
                concerns=item.get("concerns", []),
                suggestions=item.get("suggestions", []),
            ))

        # 解析 relations
        relations = []
        relation_items = verify_data.get("relations", [])
        for item in relation_items:
            relations.append(FindingRelation(
                between=item.get("between", []),
                relation_type=item.get("relation_type", "perspective_difference"),
                description=item.get("description", ""),
            ))

        logger.info(
            "VerificationAgent: LLM call successful  assessments=%s  relations=%s",
            len(assessments), len(relations),
        )
        return assessments, relations

    def _mock_assess(
        self,
        findings: list[dict[str, Any]],
        template: str,
    ) -> tuple[list[CredibilityAssessment], list[FindingRelation]]:
        """生成确定性 mock 可信度评估（用于开发和测试）

        为每个 finding 生成中等偏上的可信度评分，
        根据模板类型生成少量关系。

        Args:
            findings: 分析要点列表
            template: 场景模板

        Returns:
            (assessments, relations) 元组
        """
        assessments = []
        for i, f in enumerate(findings):
            # 根据 finding 的置信度生成一致的可信度评分
            base_cred = f.get("confidence", 0.7)
            # 添加小幅随机扰动（基于索引确定性）
            offsets = [
                (0.05, -0.03, 0.02, -0.01),   # f1
                (-0.02, 0.04, -0.01, 0.03),   # f2
                (0.03, -0.02, -0.04, 0.05),   # f3
                (-0.04, 0.03, 0.01, -0.02),   # f4
                (0.01, -0.01, 0.03, -0.04),   # f5
            ]
            offsets_i = offsets[i % len(offsets)]
            evidence = min(0.95, max(0.3, base_cred + offsets_i[0]))
            source = min(0.95, max(0.3, base_cred + offsets_i[1]))
            reasoning = min(0.95, max(0.3, base_cred + offsets_i[2]))
            consistency = min(0.95, max(0.3, base_cred + offsets_i[3]))
            overall = round(evidence * 0.3 + source * 0.2 + reasoning * 0.3 + consistency * 0.2, 2)

            assessments.append(CredibilityAssessment(
                finding_id=f["id"],
                evidence_strength=round(evidence, 2),
                source_reliability=round(source, 2),
                reasoning_soundness=round(reasoning, 2),
                data_consistency=round(consistency, 2),
                overall_credibility=overall,
                assessment=f"评估完成：{f['claim'][:50]}...",
                concerns=["此为 mock 评估"] if i == 0 else [],
                suggestions=["建议补充更多数据"] if i == 0 else [],
            ))

        # 根据模板生成 mock 关系
        relations: list[FindingRelation] = []
        if len(findings) >= 2:
            if template == "finance":
                relations.append(FindingRelation(
                    between=[findings[0]["id"], findings[1]["id"]],
                    relation_type="perspective_difference",
                    description=f"{findings[0]['id']} 与 {findings[1]['id']} 从不同维度分析财务指标，各自可信",
                ))
            elif template == "legal":
                relations.append(FindingRelation(
                    between=[findings[0]["id"], findings[1]["id"]],
                    relation_type="tension",
                    description=f"{findings[0]['id']} 与 {findings[1]['id']} 在法律解释上存在张力，需进一步分析判例",
                ))
            elif template == "general" and len(findings) >= 3:
                relations.append(FindingRelation(
                    between=[findings[0]["id"], findings[2]["id"]],
                    relation_type="perspective_difference",
                    description=f"{findings[0]['id']}（技术维度）与 {findings[2]['id']}（市场维度）观察角度不同",
                ))

        logger.info(
            "Mock verification complete  assessments=%s  relations=%s",
            len(assessments), len(relations),
        )
        return assessments, relations