"""事件存储 — SQLite 后端的事件持久化

负责：
1. 每个会话一个 SQLite 数据库文件
2. 追加式事件写入（不可变日志）
3. 事件查询（按版本范围、按类型）
4. 快照管理（定期保存状态快照以加速恢复）
5. 崩溃恢复（从 WAL 文件重建）

设计文档 § 2.1 — 事件存储
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from app.schemas.machine_wire import Event

logger = logging.getLogger(__name__)

# SQLite 生产优化 PRAGMA
# - WAL 模式：读写不阻塞
# - wal_autocheckpoint=2000：每 2000 页检查点，减少 I/O 抖动
# - cache_size=-64000：64MB 页面缓存，提升读性能
# - synchronous=NORMAL：WAL 模式下足够安全
# - busy_timeout=5000：等待锁释放 5 秒
PRAGMAS = """
PRAGMA journal_mode=WAL;
PRAGMA wal_autocheckpoint=2000;
PRAGMA cache_size=-64000;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
"""


@dataclass
class Snapshot:
    """状态快照

    Attributes:
        version: 快照对应的事件版本
        state: 序列化的状态字典
        merkle_root: 快照时的 Merkle 根哈希
    """
    version: int
    state: dict
    merkle_root: str


class SessionEventStore:
    """会话事件存储 — 每个会话一个 SQLite 数据库

    提供追加式事件写入、事件查询和快照管理功能。
    """

    def __init__(self, session_id: str, base_dir: Path) -> None:
        """初始化事件存储

        创建或打开 SQLite 数据库，初始化表结构。

        Args:
            session_id: 会话标识
            base_dir: 数据库文件存储目录
        """
        self.session_id = session_id
        base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = base_dir / f"{session_id}.db"
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(PRAGMAS)
        self._init_tables()
        logger.debug("EventStore opened  sess=%s  db=%s", session_id, self.db_path)

    def _init_tables(self) -> None:
        """初始化数据库表结构

        创建 events 表和 snapshots 表（如果不存在）。
        """
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                version         INTEGER PRIMARY KEY,
                event_type      TEXT NOT NULL,
                actor           TEXT NOT NULL,
                payload         TEXT NOT NULL,
                metadata        TEXT NOT NULL DEFAULT '{}',
                semantic_digest TEXT NOT NULL DEFAULT '',
                event_hash      TEXT NOT NULL,
                created_at      TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                version     INTEGER PRIMARY KEY,
                state       TEXT NOT NULL,
                merkle_root TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lineage (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                data        TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # 事件追加
    # ------------------------------------------------------------------

    def append(self, event: Event) -> Event:
        """追加一个事件到存储

        分配版本号（自增），计算事件哈希，写入数据库。

        Args:
            event: 要追加的事件（不含 version 和 event_hash）

        Returns:
            已保存的事件（包含分配的 version 和 event_hash）
        """
        version = self._next_version()
        event.version = version
        event.created_at = datetime.now(timezone.utc).isoformat()
        event.event_hash = event.compute_hash()

        # actor 可能是 LlmConfig（Pydantic 模型）或字符串（如 "rollback_controller"）
        actor_str = (
            event.actor.model_dump_json()
            if isinstance(event.actor, BaseModel)
            else str(event.actor)
        )
        self.conn.execute(
            """INSERT INTO events (version, event_type, actor, payload, metadata, semantic_digest, event_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                version,
                event.event_type,
                actor_str,
                json.dumps(event.payload, ensure_ascii=False),
                json.dumps(event.metadata, ensure_ascii=False),
                event.semantic_digest,
                event.event_hash,
                event.created_at,
            ),
        )
        self.conn.commit()
        return event

    # ------------------------------------------------------------------
    # 事件查询
    # ------------------------------------------------------------------

    def list_events(self) -> list[Event]:
        """列出所有事件（按版本升序）

        Returns:
            事件列表
        """
        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY version ASC",
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_events(
        self,
        from_version: int = 1,
        to_version: int | None = None,
    ) -> list[Event]:
        """获取指定版本范围的事件

        Args:
            from_version: 起始版本（含）
            to_version: 结束版本（含），None 表示到最新

        Returns:
            事件列表
        """
        if to_version is None:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE version >= ? ORDER BY version ASC",
                (from_version,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE version >= ? AND version <= ? ORDER BY version ASC",
                (from_version, to_version),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def latest_synthesis(self) -> Event | None:
        """获取最新的 SynthesisGenerated 或 SynthesisRestored 事件

        Returns:
            最新的事件，如果不存在则返回 None
        """
        row = self.conn.execute(
            """SELECT * FROM events
               WHERE event_type IN ('SynthesisGenerated', 'SynthesisRestored')
               ORDER BY version DESC LIMIT 1""",
        ).fetchone()
        return self._row_to_event(row) if row else None

    # ------------------------------------------------------------------
    # 快照管理
    # ------------------------------------------------------------------

    def save_snapshot(
        self,
        version: int,
        state: dict,
        merkle_root: str,
    ) -> None:
        """保存状态快照

        Args:
            version: 当前事件版本
            state: 要保存的状态字典
            merkle_root: 当前 Merkle 根哈希
        """
        self.conn.execute(
            """INSERT OR REPLACE INTO snapshots (version, state, merkle_root, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                version,
                json.dumps(state, ensure_ascii=False),
                merkle_root,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def get_latest_snapshot(self, max_version: int | None = None) -> Snapshot | None:
        """获取最新的状态快照

        Args:
            max_version: 最大版本限制，None 表示不限

        Returns:
            快照对象，如果不存在则返回 None
        """
        if max_version is None:
            row = self.conn.execute(
                "SELECT * FROM snapshots ORDER BY version DESC LIMIT 1",
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM snapshots WHERE version <= ? ORDER BY version DESC LIMIT 1",
                (max_version,),
            ).fetchone()
        if row is None:
            return None
        return Snapshot(
            version=row["version"],
            state=json.loads(row["state"]),
            merkle_root=row["merkle_root"],
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _next_version(self) -> int:
        """获取下一个事件版本号

        Returns:
            下一个可用的版本号
        """
        row = self.conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS nv FROM events").fetchone()
        return row["nv"]

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        """将 SQLite 行转换为 Event 对象

        Args:
            row: SQLite 查询结果行

        Returns:
            Event 对象
        """
        from app.schemas.machine_wire import LlmConfig
        # actor 可能是 JSON 序列化的 LlmConfig 字典，也可能是纯字符串（如 "rollback_controller"）
        try:
            actor_raw = json.loads(row["actor"])
            if isinstance(actor_raw, dict):
                actor = LlmConfig(**actor_raw)
            else:
                actor = str(actor_raw)
        except (json.JSONDecodeError, TypeError):
            # 纯字符串情况（如 "rollback_controller"），直接使用
            actor = row["actor"]
        # sqlite3.Row 不支持 .get()，使用 dict() 转换或使用 in 检查
        try:
            semantic_digest = row["semantic_digest"]
        except (KeyError, IndexError):
            semantic_digest = ""
        return Event(
            version=row["version"],
            event_type=row["event_type"],
            actor=actor,
            payload=json.loads(row["payload"]),
            metadata=json.loads(row["metadata"]),
            semantic_digest=semantic_digest,
            event_hash=row["event_hash"],
            created_at=row["created_at"],
        )

    def close(self) -> None:
        """关闭数据库连接"""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()
            self.conn.close()
            logger.debug("EventStore closed  sess=%s", self.session_id)
        except Exception:
            logger.exception("Error closing EventStore %s", self.session_id)
