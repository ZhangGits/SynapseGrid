"""成本追踪器 — 跟踪每次 LLM 调用的 Token 消耗和费用

负责：
1. 记录每次 LLM 调用的输入/输出 Token 数
2. 根据模型定价计算费用
3. 提供会话级别的成本汇总
4. 支持预算限制检查

设计文档 § 2.5 — 成本追踪
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 模型定价表（美元/1K tokens）
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4.1-mini": {"input": 0.0004, "output": 0.0016},
    "claude-3-5-sonnet-latest": {"input": 0.003, "output": 0.015},
    "claude-3-5-haiku-latest": {"input": 0.0008, "output": 0.004},
    "claude-3-opus-latest": {"input": 0.015, "output": 0.075},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
    "qwen-plus": {"input": 0.0008, "output": 0.002},
    "qwen-max": {"input": 0.002, "output": 0.006},
    "qwen-turbo": {"input": 0.0003, "output": 0.0006},
    "moonshot-v1-8k": {"input": 0.012, "output": 0.012},
    "moonshot-v1-32k": {"input": 0.024, "output": 0.024},
    "moonshot-v1-128k": {"input": 0.06, "output": 0.06},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
    "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
}


class CostTracker:
    """成本追踪器

    跟踪会话级别的 LLM 调用成本，支持预算限制检查。
    """

    def __init__(self) -> None:
        self._session_costs: dict[str, list[dict[str, Any]]] = {}

    def record_call(
        self,
        session_id: str,
        agent: str,
        model: str,
        tokens_input: int,
        tokens_output: int,
    ) -> dict[str, Any]:
        """记录一次 LLM 调用

        根据模型定价表计算费用。

        Args:
            session_id: 会话标识
            agent: Agent 名称
            model: 模型名称
            tokens_input: 输入 Token 数
            tokens_output: 输出 Token 数

        Returns:
            包含 agent、model、usd、tokens 等信息的记录字典
        """
        pricing = MODEL_PRICING.get(model, {"input": 0.001, "output": 0.002})
        cost_usd = (
            tokens_input * pricing["input"] / 1000
            + tokens_output * pricing["output"] / 1000
        )
        record = {
            "agent": agent,
            "model": model,
            "usd": round(cost_usd, 6),
            "tokens": tokens_input + tokens_output,
        }
        self._session_costs.setdefault(session_id, []).append(record)
        logger.debug(
            "Cost record  sess=%s  agent=%s  model=%s  usd=%.6f  tokens=%s",
            session_id, agent, model, cost_usd, tokens_input + tokens_output,
        )
        return record

    def get_session_costs(self, session_id: str) -> list[dict[str, Any]]:
        """获取会话的所有成本记录

        Args:
            session_id: 会话标识

        Returns:
            成本记录列表
        """
        return self._session_costs.get(session_id, [])

    def get_total_cost(self, session_id: str) -> float:
        """获取会话的总费用

        Args:
            session_id: 会话标识

        Returns:
            总费用（美元）
        """
        return sum(
            r["usd"] for r in self._session_costs.get(session_id, [])
        )

    def check_budget(self, session_id: str, budget_usd: float) -> bool:
        """检查是否超出预算

        Args:
            session_id: 会话标识
            budget_usd: 预算上限（美元）

        Returns:
            是否在预算内（True = 未超预算）
        """
        total = self.get_total_cost(session_id)
        within = total <= budget_usd
        if not within:
            logger.warning(
                "Budget exceeded  sess=%s  total=%.4f  budget=%.4f",
                session_id, total, budget_usd,
            )
        return within
