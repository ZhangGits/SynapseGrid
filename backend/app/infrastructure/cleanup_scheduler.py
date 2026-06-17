"""清理调度器 — 管理会话的延迟清理

负责：
1. 调度会话在指定延迟后清理
2. 持久化调度信息到 SQLite（重启后恢复）
3. 启动时补偿（检查是否有到期未清理的会话）
4. 调用 purge_handler 执行实际清理

设计文档 § 2.1 — 会话生命周期
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

CLEANUP_DB = Path("/tmp/synapse_sessions/cleanup_schedule.db")


class CleanupScheduler:
    """清理调度器

    管理会话的延迟清理调度，支持持久化和启动补偿。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._purge_handler: Callable[[str], Awaitable[None]] | None = None
        self._running = False

    async def start(
        self,
        purge_handler: Callable[[str], Awaitable[None]],
    ) -> None:
        """启动清理调度器

        初始化持久化数据库，恢复未完成的调度。

        Args:
            purge_handler: 清理回调函数，接收 session_id 参数
        """
        self._purge_handler = purge_handler
        self._init_db()
        self._running = True
        # 启动时补偿：恢复所有未完成的调度
        pending = self._load_pending()
        for session_id, scheduled_at in pending:
            remaining = scheduled_at - datetime.now(timezone.utc)
            delay = max(remaining.total_seconds(), 0)
            logger.info(
                "Recovering cleanup schedule  sess=%s  delay=%.0fs",
                session_id, delay,
            )
            self._schedule_task(session_id, delay)
        logger.info("CleanupScheduler started  recovered=%s", len(pending))

    async def stop(self) -> None:
        """停止清理调度器

        取消所有待处理的清理任务。
        """
        self._running = False
        for session_id, task in list(self._tasks.items()):
            task.cancel()
        self._tasks.clear()
        logger.info("CleanupScheduler stopped")

    def schedule(self, session_id: str, delay_seconds: int) -> None:
        """调度一个会话的清理

        Args:
            session_id: 要清理的会话标识
            delay_seconds: 延迟秒数
        """
        scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        self._persist_schedule(session_id, scheduled_at)
        self._schedule_task(session_id, delay_seconds)
        logger.debug(
            "Cleanup scheduled  sess=%s  at=%s",
            session_id, scheduled_at.isoformat(),
        )

    def mark_purged(self, session_id: str) -> None:
        """标记会话已清理

        从持久化调度中移除。

        Args:
            session_id: 已清理的会话标识
        """
        self._remove_schedule(session_id)
        self._tasks.pop(session_id, None)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _schedule_task(self, session_id: str, delay: float) -> None:
        """创建一个异步清理任务

        Args:
            session_id: 会话标识
            delay: 延迟秒数
        """
        async def _cleanup():
            try:
                await asyncio.sleep(delay)
                if self._purge_handler and self._running:
                    await self._purge_handler(session_id)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Cleanup failed for session %s", session_id)

        # 取消已有的任务（如果存在）
        existing = self._tasks.get(session_id)
        if existing and not existing.done():
            existing.cancel()
        self._tasks[session_id] = asyncio.create_task(_cleanup())

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """初始化持久化数据库"""
        CLEANUP_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(CLEANUP_DB))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cleanup_schedule (
                    session_id    TEXT PRIMARY KEY,
                    scheduled_at  TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _persist_schedule(self, session_id: str, scheduled_at: datetime) -> None:
        """持久化调度信息

        Args:
            session_id: 会话标识
            scheduled_at: 计划清理时间
        """
        conn = sqlite3.connect(str(CLEANUP_DB))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cleanup_schedule (session_id, scheduled_at) VALUES (?, ?)",
                (session_id, scheduled_at.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def _remove_schedule(self, session_id: str) -> None:
        """从持久化调度中移除

        Args:
            session_id: 会话标识
        """
        conn = sqlite3.connect(str(CLEANUP_DB))
        try:
            conn.execute(
                "DELETE FROM cleanup_schedule WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_pending(self) -> list[tuple[str, datetime]]:
        """加载所有未完成的调度

        Returns:
            (session_id, scheduled_at) 元组列表
        """
        conn = sqlite3.connect(str(CLEANUP_DB))
        try:
            rows = conn.execute(
                "SELECT session_id, scheduled_at FROM cleanup_schedule ORDER BY scheduled_at ASC",
            ).fetchall()
            result = []
            now = datetime.now(timezone.utc)
            for row in rows:
                scheduled_at = datetime.fromisoformat(row[1])
                if scheduled_at > now:
                    result.append((row[0], scheduled_at))
            return result
        finally:
            conn.close()
