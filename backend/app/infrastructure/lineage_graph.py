"""谱系图 — 追踪事件之间的依赖关系

负责：
1. 维护事件之间的依赖关系图
2. 支持谱系图的序列化和反序列化
3. 提供 to_wire 方法供 API 响应使用
4. 持久化到 SQLite 以便跨进程恢复

设计文档 § 2.4 — 谱系图
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.schemas.machine_wire import Event

logger = logging.getLogger(__name__)


class SessionLineageGraph:
    """会话谱系图

    追踪事件之间的依赖关系，支持序列化和持久化。
    """

    def __init__(self) -> None:
        """初始化空的谱系图"""
        self.nodes: list[dict[str, str]] = []
        self.edges: list[dict[str, str]] = []

    def apply(self, event: Event) -> None:
        """应用一个事件到谱系图

        根据事件类型添加节点和边。

        Args:
            event: 要应用的事件
        """
        node_id = f"v{event.version}"
        node_type = event.event_type
        label = self._node_label(event)

        self.nodes.append({
            "id": node_id,
            "type": node_type,
            "label": label,
        })

        # 添加边：连接到前一个事件
        if event.version > 1:
            prev_id = f"v{event.version - 1}"
            self.edges.append({
                "source": prev_id,
                "target": node_id,
                "relation": "next",
            })

    def to_wire(self) -> dict[str, Any]:
        """返回谱系图的线格式表示（供 API 响应使用）

        Returns:
            包含 nodes 和 edges 的字典
        """
        return {
            "nodes": self.nodes,
            "edges": self.edges,
        }

    def persist_to_store(self, conn: sqlite3.Connection) -> None:
        """将谱系图持久化到 SQLite

        Args:
            conn: SQLite 数据库连接
        """
        data = json.dumps(self.to_wire(), ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO lineage (id, data, updated_at) VALUES (1, ?, ?)",
            (data, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    @classmethod
    def load_from_events(
        cls,
        conn: sqlite3.Connection,
        events: list[Event],
    ) -> SessionLineageGraph:
        """从事件列表加载谱系图

        优先从 SQLite 恢复，如果不存在则从事件重建。

        Args:
            conn: SQLite 数据库连接
            events: 事件列表

        Returns:
            重建的谱系图
        """
        # 尝试从 SQLite 恢复
        try:
            row = conn.execute(
                "SELECT data FROM lineage WHERE id = 1",
            ).fetchone()
            if row:
                data = json.loads(row["data"])
                graph = cls()
                graph.nodes = data.get("nodes", [])
                graph.edges = data.get("edges", [])
                return graph
        except Exception:
            logger.debug("Could not load lineage from store, rebuilding from events")

        # 从事件重建
        graph = cls()
        for event in events:
            graph.apply(event)
        return graph

    @staticmethod
    def _node_label(event: Event) -> str:
        """生成节点的显示标签

        Args:
            event: 事件对象

        Returns:
            节点的显示标签
        """
        labels = {
            "TaskStarted": "任务开始",
            "FindingReported": "分析要点",
            "FindingValidated": "已验证",
            "FindingRolledBack": "已回退",
            "ConflictDetected": "矛盾检测",
            "AggregationCompleted": "聚合完成",
            "SynthesisGenerated": "综合生成",
            "SynthesisRestored": "综合恢复",
            "CanvasUpdated": "画布更新",
            "AgentExecution": "Agent 执行",
        }
        return labels.get(event.event_type, event.event_type)
