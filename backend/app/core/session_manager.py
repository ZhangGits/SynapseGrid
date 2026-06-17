"""会话生命周期管理模块 — 创建、查询、追加、关闭、清理

符合设计文档 § 2.1。关键特性：

* 每个会话一个 SQLite 数据库（会话级隔离）
* 每个会话一个单写者 ``asyncio.Queue`` — 无锁竞争
* 每次追加后，谱系图序列化回会话自己的 SQLite，以便在多进程部署中存活
* 清理委托给 ``CleanupScheduler``（持久调度 + 启动补偿）
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.core.state_machine import SessionStateProjection
from app.infrastructure.cleanup_scheduler import CleanupScheduler
from app.infrastructure.event_store import SessionEventStore
from app.infrastructure.lineage_graph import SessionLineageGraph
from app.infrastructure.merkle import merkle_root
from app.schemas.machine_wire import Event

logger = logging.getLogger(__name__)

BASE_DIR = Path(tempfile.gettempdir()) / "synapse_sessions"
SNAPSHOT_INTERVAL = 50


@dataclass
class SessionContext:
    """会话上下文：包含会话的所有资源和状态

    Attributes:
        session_id: 会话唯一标识
        event_store: 事件存储（SQLite 后端）
        projection: 内存状态投影
        lineage: 谱系图
        write_queue: 单写者异步队列
        writer_task: 写者协程任务
        created_at: 创建时间（UTC）
    """
    session_id: str
    event_store: SessionEventStore
    projection: SessionStateProjection
    lineage: SessionLineageGraph
    write_queue: asyncio.Queue[tuple[Event | None, asyncio.Future[Event] | None]]
    writer_task: asyncio.Task[None]
    created_at: datetime  # utc


class SessionContextManager:
    """会话上下文管理器 — 活动会话及其每会话资源的中央注册表

    管理会话的创建、查询、关闭、分支和清理调度。
    使用单写者队列模式确保每个会话的事件写入是串行化的。
    """

    def __init__(self) -> None:
        self.active_sessions: dict[str, SessionContext] = {}
        self._cleanup = CleanupScheduler()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动会话管理器：创建基础目录并启动清理调度器"""
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        await self._cleanup.start(purge_handler=self._purge_handler)

    async def stop(self) -> None:
        """停止会话管理器：关闭所有活动会话并停止清理调度器"""
        for session_id in list(self.active_sessions):
            await self.close_session(session_id, schedule=False)
        await self._cleanup.stop()

    # ------------------------------------------------------------------
    # 会话 CRUD
    # ------------------------------------------------------------------

    def create_session(self, user_id: str = "user001") -> SessionContext:
        """创建一个新会话

        生成唯一 session_id，创建事件存储，从已有事件重建谱系图，
        启动单写者循环。

        Args:
            user_id: 用户标识，默认为 "user001"

        Returns:
            新创建的会话上下文
        """
        session_id = (
            f"sess_{user_id}_{uuid4().hex[:8]}"
            f"_{int(datetime.now(timezone.utc).timestamp())}"
        )
        store = SessionEventStore(session_id, BASE_DIR)
        logger.info("Session created  id=%s  db=%s", session_id, store.db_path)

        # 如果已有序列化的谱系图，从事件重建
        lineage = SessionLineageGraph.load_from_events(store.conn, store.list_events())

        # 先创建 SessionContext（writer_task 使用占位，稍后替换）
        ctx = SessionContext(
            session_id=session_id,
            event_store=store,
            projection=SessionStateProjection(),
            lineage=lineage,
            write_queue=asyncio.Queue(),
            writer_task=asyncio.create_task(self._noop()),  # 占位，稍后替换
            created_at=datetime.now(timezone.utc),
        )
        # 替换为真正的 writer_loop（此时 ctx 已定义，可以安全引用）
        ctx.writer_task = asyncio.create_task(self._writer_loop(ctx))
        self.active_sessions[session_id] = ctx
        logger.debug("Writer loop started for %s", session_id)
        return ctx

    def get_session(self, session_id: str) -> SessionContext | None:
        """根据 session_id 获取会话上下文

        Args:
            session_id: 会话标识

        Returns:
            会话上下文，如果不存在则返回 None
        """
        return self.active_sessions.get(session_id)

    # ------------------------------------------------------------------
    # 事件追加（通过单写者队列）
    # ------------------------------------------------------------------

    async def append_event(self, ctx: SessionContext, event: Event) -> Event:
        """追加事件到会话

        通过单写者队列将事件入队，等待持久写入完成，
        然后更新内存投影和谱系图。

        Args:
            ctx: 会话上下文
            event: 要追加的事件

        Returns:
            已保存的事件（包含分配的版本号和哈希）
        """
        future: asyncio.Future[Event] = asyncio.get_running_loop().create_future()
        await ctx.write_queue.put((event, future))
        saved = await future  # 这是已分配版本/哈希的事件

        logger.debug(
            "Event written  sess=%s  v=%s  type=%s  hash=%s",
            ctx.session_id, saved.version, saved.event_type,
            saved.event_hash[:20] if saved.event_hash else "-",
        )

        # 2. 投影到内存（仅在成功写入后）
        ctx.projection.apply(saved)
        ctx.lineage.apply(saved)

        # 3. 将谱系图持久化回 SQLite（设计文档 § 2.4）
        ctx.lineage.persist_to_store(ctx.event_store.conn)

        # 4. 定期快照
        if saved.version % SNAPSHOT_INTERVAL == 0:
            ctx.event_store.save_snapshot(
                saved.version,
                ctx.projection.dump(),
                ctx.projection.merkle_root,
            )
            logger.info("Snapshot saved  sess=%s  version=%s", ctx.session_id, saved.version)

        return saved

    # ------------------------------------------------------------------
    # 关闭与清理
    # ------------------------------------------------------------------

    async def close_session(
        self,
        session_id: str,
        schedule: bool = True,
        delay_seconds: int = 300,
    ) -> None:
        """关闭会话

        可选择调度清理，发送毒丸信号停止写者循环，关闭事件存储。

        Args:
            session_id: 要关闭的会话标识
            schedule: 是否调度清理（默认 True）
            delay_seconds: 清理延迟秒数（默认 300）
        """
        ctx = self.active_sessions.get(session_id)
        if not ctx:
            logger.warning("close_session: session not found  id=%s", session_id)
            return
        if schedule:
            self.schedule_cleanup(session_id, delay_seconds)
            logger.info("Cleanup scheduled  id=%s  delay=%ss", session_id, delay_seconds)
        await ctx.write_queue.put((None, None))
        await ctx.writer_task
        ctx.event_store.close()
        logger.info("Session closed  id=%s  events=%s", session_id, ctx.projection.current_version)

    def schedule_cleanup(self, session_id: str, delay_seconds: int = 300) -> None:
        """调度会话清理

        Args:
            session_id: 会话标识
            delay_seconds: 延迟秒数
        """
        self._cleanup.schedule(session_id, delay_seconds)

    async def branch_session(self, session_id: str) -> str:
        """创建会话的分支（时间点分叉）

        复制 SQLite 文件并创建新的会话上下文指向复制的数据库。

        Args:
            session_id: 源会话标识

        Returns:
            新分支的会话标识

        Raises:
            ValueError: 源会话不存在时抛出
        """
        import shutil
        ctx = self.get_session(session_id)
        if ctx is None:
            raise ValueError(f"Session {session_id} not found")

        new_id = (
            f"sess_branch_{uuid4().hex[:8]}"
            f"_{int(datetime.now(timezone.utc).timestamp())}"
        )
        # 复制 SQLite 文件
        src = ctx.event_store.db_path
        dst = BASE_DIR / f"{new_id}.db"
        ctx.event_store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        ctx.event_store.conn.commit()
        shutil.copy2(src, dst)

        # 创建指向复制数据库的新会话上下文
        new_store = SessionEventStore(new_id, BASE_DIR)
        logger.info("Branch created  id=%s  parent=%s  src=%s  dst=%s", new_id, session_id, src, new_store.db_path)
        # 先创建 SessionContext（writer_task 使用占位，稍后替换）
        new_ctx = SessionContext(
            session_id=new_id,
            event_store=new_store,
            projection=SessionStateProjection(),
            lineage=SessionLineageGraph.load_from_events(new_store.conn, new_store.list_events()),
            write_queue=asyncio.Queue(),
            writer_task=asyncio.create_task(self._noop()),  # 占位，稍后替换
            created_at=datetime.now(timezone.utc),
        )
        new_ctx.projection.rebuild(new_store.list_events())
        # 替换为真正的 writer_loop（此时 new_ctx 已定义，可以安全引用）
        new_ctx.writer_task = asyncio.create_task(self._writer_loop(new_ctx))
        self.active_sessions[new_id] = new_ctx
        return new_id

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _noop(self) -> None:
        """空操作协程，用作 writer_task 的初始占位"""
        pass

    async def _writer_loop(self, ctx: SessionContext) -> None:
        """单写者循环 — 唯一接触此会话 SQLite 的协程

        从队列中取出事件，写入事件存储，然后设置 future 结果。
        收到 (None, None) 毒丸信号时退出循环。
        异常时自动重启（最多 3 次），防止单个会话崩溃影响其他会话。
        """
        restart_count = 0
        max_restarts = 3

        while True:
            try:
                event, future = await ctx.write_queue.get()
                if event is None:  # 毒丸信号
                    ctx.write_queue.task_done()
                    break
                try:
                    saved = ctx.event_store.append(event)
                    future.set_result(saved)
                except Exception as exc:
                    logger.exception("Event write failed for session %s", ctx.session_id)
                    future.set_exception(exc)
                finally:
                    ctx.write_queue.task_done()
            except Exception:
                restart_count += 1
                logger.exception(
                    "Writer loop crashed for session %s  restart=%s/%s",
                    ctx.session_id, restart_count, max_restarts,
                )
                if restart_count >= max_restarts:
                    logger.error("Writer loop exhausted restarts for %s", ctx.session_id)
                    # 通知所有等待中的 future
                    try:
                        while not ctx.write_queue.empty():
                            event, future = ctx.write_queue.get_nowait()
                            if event is not None and future is not None and not future.done():
                                future.set_exception(RuntimeError("Writer loop crashed"))
                            ctx.write_queue.task_done()
                    except Exception:
                        pass
                    break
                # 短暂等待后重试
                await asyncio.sleep(0.5)

    async def _purge_handler(self, session_id: str) -> None:
        """由 CleanupScheduler 调用，当会话到期需要删除时执行

        从活动会话中移除，关闭事件存储，删除 SQLite 文件（包括 WAL/SHM）。
        """
        logger.info("Purging session  id=%s", session_id)
        ctx = self.active_sessions.pop(session_id, None)
        if ctx:
            await ctx.write_queue.put((None, None))
            await ctx.writer_task
            ctx.event_store.close()
        # 删除 SQLite 文件（包括 WAL / SHM）
        removed = 0
        for path in BASE_DIR.glob(f"{session_id}.db*"):
            try:
                path.unlink()
                removed += 1
            except Exception:
                logger.warning("Could not remove %s", path)
        self._cleanup.mark_purged(session_id)
        logger.info("Session purged  id=%s  files_removed=%s", session_id, removed)


session_manager = SessionContextManager()
