"""上下文净化过滤器 — 根据 Agent 类型过滤无关事件

每个 Agent 只接收其任务所需的最小上下文：
- Research: 只接收 TaskStarted（不含历史 Finding 详情）
- Verification: 接收 TaskStarted + FindingReported
- Synthesis: 接收 FindingValidated + ConflictDetected + FindingRolledBack
"""

from __future__ import annotations

from typing import Any

from app.schemas.machine_wire import Event


class ContextFilter:
    """上下文净化过滤器"""

    # Agent → 需要的事件类型映射
    AGENT_CONTEXT_MAP = {
        "research": ["TaskStarted"],
        "verification": ["TaskStarted", "FindingReported"],
        "synthesis": ["FindingValidated", "ConflictDetected", "FindingRolledBack", "SynthesisGenerated"],
    }

    @staticmethod
    def filter_for_agent(events: list[Event], agent_name: str) -> list[Event]:
        """过滤事件列表，只保留指定 Agent 需要的事件

        Args:
            events: 完整事件列表
            agent_name: Agent 名称（research/verification/synthesis）

        Returns:
            过滤后的事件列表
        """
        allowed_types = ContextFilter.AGENT_CONTEXT_MAP.get(agent_name, [])
        return [e for e in events if e.event_type in allowed_types]

    @staticmethod
    def filter_payload_for_agent(event: Event, agent_name: str) -> Event:
        """过滤单个事件的 payload，移除 Agent 不需要的字段

        Args:
            event: 原始事件
            agent_name: Agent 名称

        Returns:
            净化后的事件（payload 已精简）
        """
        # 默认不修改
        if agent_name not in ("research", "verification", "synthesis"):
            return event

        # 创建新事件，精简 payload
        new_payload = dict(event.payload)

        if agent_name == "research":
            # Research 不需要看到其他 finding 的详细证据
            if event.event_type == "TaskStarted":
                # 保留 prompt 和 template，移除 conversation_history（太长的历史）
                new_payload.pop("conversation_history", None)
        elif agent_name == "verification":
            # Verification 不需要 LLM 原始响应
            if event.event_type == "FindingReported":
                finding = new_payload.get("finding", {})
                # 保留核心字段，移除过长的 source/evidence
                finding.pop("source", None)
                new_payload["finding"] = finding
        elif agent_name == "synthesis":
            # Synthesis 不需要 Research 的原始数据
            if event.event_type in ("FindingValidated", "FindingRolledBack"):
                # 只保留 finding_id，移除完整 finding 详情
                pass  # payload 已经是精简的

        return Event(
            version=event.version,
            event_type=event.event_type,
            actor=event.actor,
            payload=new_payload,
            metadata=event.metadata,
            semantic_digest=event.semantic_digest,
            event_hash=event.event_hash,
            created_at=event.created_at,
        )

    @staticmethod
    def estimate_savings(events: list[Event], agent_name: str) -> dict[str, Any]:
        """估算上下文净化节省的 Token

        Args:
            events: 完整事件列表
            agent_name: Agent 名称

        Returns:
            节省统计
        """
        import json

        full_json = json.dumps([e.model_dump() for e in events], ensure_ascii=False)

        filtered = ContextFilter.filter_for_agent(events, agent_name)
        # 应用 payload 精简
        cleaned = [ContextFilter.filter_payload_for_agent(e, agent_name) for e in filtered]
        cleaned_json = json.dumps([e.model_dump() for e in cleaned], ensure_ascii=False)

        return {
            "agent": agent_name,
            "original_events": len(events),
            "filtered_events": len(filtered),
            "original_chars": len(full_json),
            "cleaned_chars": len(cleaned_json),
            "savings": len(full_json) - len(cleaned_json),
            "savings_percent": round((len(full_json) - len(cleaned_json)) / len(full_json) * 100, 1) if full_json else 0,
        }