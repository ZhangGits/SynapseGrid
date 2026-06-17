"""画布用户意图模型 — IntentPayload 和 ActionLogItem

定义前端画布交互时发送的用户意图数据结构，
用于 process_feedback 端点解析用户操作。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ActionLogItem(BaseModel):
    """用户操作日志项

    Attributes:
        action: 操作类型（drag/click/input）
        target_id: 目标组件 ID
        new_position: 新位置（可选）
        detail: 操作详情（可选）
    """
    action: str = ""
    target_id: str = ""
    new_position: dict[str, float] | None = None
    detail: str | None = None


class IntentPayload(BaseModel):
    """用户意图负载

    Attributes:
        type: 意图类型
            - LAYOUT_ADJUST: 调整布局
            - DATA_FOCUS: 数据聚焦
            - STYLE_CHANGE: 样式变更
            - EXPLORATORY: 探索性查询
            - COMPOUND_ACTION: 复合操作
        base_version: 当前画布版本号
        targets: 目标组件 ID 列表
        action_log: 用户操作日志
        user_text: 用户输入的自然语言文本
    """
    type: str = "EXPLORATORY"
    base_version: int = 1
    targets: list[str] = Field(default_factory=list)
    action_log: list[ActionLogItem] = Field(default_factory=list)
    user_text: str = ""
