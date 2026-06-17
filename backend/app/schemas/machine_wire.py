"""核心数据模型 — 事件、LLM 配置、任务请求、成本记录

定义系统中所有核心数据模型，包括：
- Event: 事件（事件溯源的核心不可变日志条目）
- LlmConfig: LLM 配置（provider、model、api_key）
- TaskRequest: 任务请求（API 入口）
- CostRecord: 成本记录
- RollbackRequest: 回退请求
- CredibilityAssessment: 可信度评估（四维度）
- FindingRelation: finding 间关系
- LogicNode / LogicEdge / LogicGraph: 论证结构图
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LlmConfig(BaseModel):
    """LLM 配置模型

    Attributes:
        provider: LLM 提供商（chatgpt/claude/deepseek/qwen/kimi/gemini/custom）
        model: 模型名称
        api_key: API 密钥
        base_url: 自定义 API 地址（可选）
    """
    provider: str = "chatgpt"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str | None = None


class Event(BaseModel):
    """事件模型 — 事件溯源的核心不可变日志条目

    Attributes:
        version: 事件版本号（自增，由存储分配）
        event_type: 事件类型（TaskStarted/FindingReported/FindingValidated 等）
        actor: 执行者（LLM 配置或字符串）
        payload: 事件负载（任意 JSON 可序列化数据）
        metadata: 元数据（用户 ID、成本等）
        semantic_digest: 语义摘要（一句话描述事件含义，用于审计层快速理解）
        event_hash: 事件哈希（SHA-256，由存储计算，包含 payload + semantic_digest）
        created_at: 创建时间（ISO 格式 UTC）
    """
    version: int = 0
    event_type: str = ""
    actor: LlmConfig | str = LlmConfig()
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    semantic_digest: str = ""  # 一句话语义摘要
    event_hash: str = ""
    created_at: str = ""

    def compute_hash(self) -> str:
        """计算事件的 SHA-256 哈希

        哈希输入 = event_type + actor + json(payload) + json(metadata) + semantic_digest + str(version)

        Returns:
            SHA-256 哈希字符串（前缀 "sha256:"）
        """
        raw = (
            f"{self.event_type}|"
            f"{self.actor.model_dump_json() if isinstance(self.actor, BaseModel) else str(self.actor)}|"
            f"{json.dumps(self.payload, sort_keys=True, ensure_ascii=False)}|"
            f"{json.dumps(self.metadata, sort_keys=True, ensure_ascii=False)}|"
            f"{self.semantic_digest}|"
            f"{self.version}"
        )
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"sha256:{h}"


class TaskRequest(BaseModel):
    """任务请求模型 — API 入口

    Attributes:
        user_id: 用户标识
        prompt: 用户输入的分析任务
        llm_research: 研究 Agent 的 LLM 配置
        llm_verification: 验证 Agent 的 LLM 配置
        llm_synthesis: 综合 Agent 的 LLM 配置
        template: 场景模板
        output_mode: 输出模式（markdown/canvas）
        conversation_history: 对话历史上下文
    """
    user_id: str = "user001"
    prompt: str = ""
    llm_research: LlmConfig | None = None
    llm_verification: LlmConfig | None = None
    llm_synthesis: LlmConfig | None = None
    template: str = "general"
    output_mode: str = "markdown"
    conversation_history: str | None = None


class CostRecord(BaseModel):
    """成本记录模型

    Attributes:
        agent: Agent 名称
        model: 模型名称
        usd: 费用（美元）
        tokens: Token 总数
    """
    agent: str = ""
    model: str = ""
    usd: float = 0.0
    tokens: int = 0


class RollbackRequest(BaseModel):
    """回退请求模型

    Attributes:
        finding_id: 要回退的分析要点 ID
        reason: 回退原因
    """
    finding_id: str
    reason: str = "User requested rollback"


# ── Phase 1 新增：可信度评估模型 ──────────────────────────────────────────


class CredibilityAssessment(BaseModel):
    """可信度评估 — 对单个 finding 的四维度独立评估

    Verification Agent 不再"检测矛盾"，而是独立评估每个 finding 的可信度。
    四个维度各自 0-1 评分，overall_credibility 是加权平均。

    Attributes:
        finding_id: 被评估的分析要点 ID
        evidence_strength: 证据强度（0-1）
        source_reliability: 来源可靠性（0-1）
        reasoning_soundness: 推理合理性（0-1）
        data_consistency: 数据一致性（0-1）
        overall_credibility: 综合可信度（加权平均）
        assessment: 一句话评估
        concerns: 顾虑列表
        suggestions: 改进建议
    """
    finding_id: str
    evidence_strength: float = 0.5
    source_reliability: float = 0.5
    reasoning_soundness: float = 0.5
    data_consistency: float = 0.5
    overall_credibility: float = 0.5
    assessment: str = ""
    concerns: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class FindingRelation(BaseModel):
    """Finding 间关系 — 描述两个 finding 之间的关系类型

    不再简单标记"矛盾"，而是区分：
    - perspective_difference: 视角差异（观察维度不同，各自可信）
    - tension: 张力（存在不一致但可调和）
    - genuine_contradiction: 真实矛盾（逻辑不可调和）

    Attributes:
        between: 涉及的 finding ID 列表
        relation_type: 关系类型
        description: 关系描述
    """
    between: list[str]
    relation_type: str  # "perspective_difference" | "tension" | "genuine_contradiction"
    description: str = ""


# ── Phase 1 新增：论证结构图模型 ──────────────────────────────────────────


class LogicNode(BaseModel):
    """论证结构节点 — 代表论证中的一个概念单元

    Attributes:
        id: 节点唯一标识
        type: 节点类型（question/conclusion/claim/evidence）
        label: 显示文本（完整文本）
        summary: 摘要（1-2 句简洁描述，由 Synthesis Agent 提取，前端画布上优先显示）
        finding_id: 关联的 finding ID（可选）
        credibility: 可信度（0-1）
        rolled_back: 是否已回退
        importance: 重要性权重（0-1）
    """
    id: str
    type: str  # "question" | "conclusion" | "claim" | "evidence"
    label: str
    summary: str | None = None
    finding_id: str | None = None
    credibility: float = 0.5
    rolled_back: bool = False
    importance: float = 0.5


class LogicEdge(BaseModel):
    """论证结构边 — 代表节点间的逻辑关系

    Attributes:
        from_id: 源节点 ID
        to_id: 目标节点 ID
        type: 边类型（supports/perspective_difference/tension/genuine_contradiction）
        description: 关系描述（可选）
    """
    from_id: str
    to_id: str
    type: str  # "supports" | "perspective_difference" | "tension" | "genuine_contradiction"
    description: str | None = None


class LogicGraph(BaseModel):
    """论证结构图 — 完整的论证结构

    由节点（概念单元）和边（逻辑关系）组成的有向图。
    前端使用 Cytoscape.js + dagre 渲染为 DAG 布局。

    Attributes:
        nodes: 节点列表
        edges: 边列表
    """
    nodes: list[LogicNode]
    edges: list[LogicEdge]


class SynthesisResult(BaseModel):
    """Synthesis Agent 的综合输出

    Canvas 模式下 Synthesis Agent 不再生成仪表盘组件，
    而是提取论证结构图 + 生成增强 Markdown。

    Attributes:
        logic_graph: 论证结构图
        enriched_markdown: 带 provenance 标签的增强 Markdown
        node_map: 节点 ID → 段落 ID 映射（用于树-叙事联动）
    """
    logic_graph: LogicGraph = Field(default_factory=lambda: LogicGraph(nodes=[], edges=[]))
    enriched_markdown: str = ""
    node_map: dict[str, str] = Field(default_factory=dict)