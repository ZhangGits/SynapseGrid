"""API 响应模型 — TaskResponse 及其子模型

定义 API 返回的完整响应结构，包括：
- TaskResponse: 顶层响应
- AuditMetadata: 审计元数据
- LineageData: 谱系数据
- RollbackOptions: 回退选项
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.machine_wire import CostRecord, LogicGraph


class AuditMetadata(BaseModel):
    """审计元数据模型

    Attributes:
        session_id: 会话标识
        merkle_root: Merkle 树根哈希
        content_signature: 内容签名（HMAC）
        findings: 分析要点列表
        conflicts: 矛盾列表
        cost_breakdown: 成本明细
        total_tokens: 总 Token 数
        event_count: 事件总数
        duration_seconds: 执行耗时（秒）
        budget_remaining: 剩余预算（可选）
        agent_traces: Agent 执行追踪（可选）
    """
    session_id: str = ""
    merkle_root: str = ""
    content_signature: str = ""
    findings: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    cost_breakdown: list[CostRecord] = Field(default_factory=list)
    total_tokens: int = 0
    event_count: int = 0
    duration_seconds: float = 0.0
    budget_remaining: float | None = None
    agent_traces: list[dict[str, Any]] | None = None


class LineageData(BaseModel):
    """谱系数据模型

    Attributes:
        nodes: 谱系节点列表
        edges: 谱系边列表
    """
    nodes: list[dict[str, str]] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)


class RollbackOptions(BaseModel):
    """回退选项模型

    Attributes:
        rollbackable_findings: 可回退的分析要点 ID 列表
        branches: 分支会话 ID 列表
    """
    rollbackable_findings: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)


class TaskResponse(BaseModel):
    """任务响应模型 — API 返回的顶层响应

    Attributes:
        session_id: 会话标识
        markdown_content: 最终报告的 Markdown 内容（纯文本，不含 provenance 标签）
        enriched_markdown: 带 provenance 标签的增强 Markdown（用于前端交互式溯源）
        canvas_schema: Canvas 模式的结构化数据（可选）
        audit_metadata: 审计元数据
        lineage_data: 谱系数据
        rollback_options: 回退选项
    """
    session_id: str = ""
    markdown_content: str = ""
    enriched_markdown: str = ""
    canvas_schema: LogicGraph | None = None
    audit_metadata: AuditMetadata = Field(default_factory=AuditMetadata)
    lineage_data: LineageData = Field(default_factory=LineageData)
    rollback_options: RollbackOptions = Field(default_factory=RollbackOptions)
