"""SACP 协议模型 — 结构化 Agent 通信协议 (Structured Agent Communication Protocol)

定义 Agent 间结构化通信的数据模型：
- AgentMessage: Agent 间消息的标准格式
- CompressedPayload: 压缩载荷（支持 TOON/JSON/Diff 格式）
- AgentMsgType: 消息类型枚举
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentMsgType(str, Enum):
    """Agent 消息类型枚举"""
    FINDINGS_REPORT = "findings_report"        # Research → Verification
    VALIDATION_RESULT = "validation_result"    # Verification → Synthesis
    SYNTHESIS_REQUEST = "synthesis_request"    # Orchestrator → Synthesis
    TASK_STARTED = "task_started"              # 任务启动
    ROLLBACK_NOTICE = "rollback_notice"        # 回退通知


class CompressedPayload(BaseModel):
    """压缩载荷 — 支持多种序列化格式"""
    format: Literal["toon", "json", "diff"] = "json"
    data: str = ""                             # 序列化后的数据
    checksum: str = ""                         # 数据校验和（SHA-256 前16位）

    @classmethod
    def from_toon(cls, data: str) -> "CompressedPayload":
        """从 TOON 格式创建载荷"""
        import hashlib
        checksum = hashlib.sha256(data.encode()).hexdigest()[:16]
        return cls(format="toon", data=data, checksum=checksum)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CompressedPayload":
        """从 JSON 格式创建载荷"""
        import hashlib, json
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        checksum = hashlib.sha256(json_str.encode()).hexdigest()[:16]
        return cls(format="json", data=json_str, checksum=checksum)

    @classmethod
    def from_diff(cls, data: str) -> "CompressedPayload":
        """从 Diff 格式创建载荷"""
        import hashlib
        checksum = hashlib.sha256(data.encode()).hexdigest()[:16]
        return cls(format="diff", data=data, checksum=checksum)

    def verify_checksum(self) -> bool:
        """验证数据完整性"""
        import hashlib
        expected = hashlib.sha256(self.data.encode()).hexdigest()[:16]
        return self.checksum == expected


class AgentMessage(BaseModel):
    """Agent 间消息的标准格式

    Attributes:
        msg_type: 消息类型
        payload: 压缩载荷（TOON/JSON/Diff）
        semantic_digest: 一句话语义摘要
        human_readable_ref: 人类可读引用（可选）
        from_agent: 发送方 Agent 名称
        to_agent: 接收方 Agent 名称
    """
    msg_type: AgentMsgType
    payload: CompressedPayload
    semantic_digest: str = ""                   # 一句话语义摘要
    human_readable_ref: str | None = None       # 人类可读引用
    from_agent: str = ""
    to_agent: str = ""

    def to_wire(self) -> dict[str, Any]:
        """序列化为有线格式"""
        return {
            "msg_type": self.msg_type.value,
            "payload": {
                "format": self.payload.format,
                "data": self.payload.data,
                "checksum": self.payload.checksum,
            },
            "semantic_digest": self.semantic_digest,
            "human_readable_ref": self.human_readable_ref,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
        }

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "AgentMessage":
        """从有线格式反序列化"""
        return cls(
            msg_type=AgentMsgType(data["msg_type"]),
            payload=CompressedPayload(**data["payload"]),
            semantic_digest=data.get("semantic_digest", ""),
            human_readable_ref=data.get("human_readable_ref"),
            from_agent=data.get("from_agent", ""),
            to_agent=data.get("to_agent", ""),
        )