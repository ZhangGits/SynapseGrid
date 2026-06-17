"""事件存储单元测试

测试 SessionEventStore 的追加、查询、快照功能。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.infrastructure.event_store import SessionEventStore
from app.schemas.machine_wire import Event, LlmConfig


@pytest.fixture
def store():
    """创建临时事件存储供测试使用"""
    tmpdir = Path(tempfile.mkdtemp())
    store = SessionEventStore("test_session", tmpdir)
    yield store
    store.close()


class TestEventStore:
    """事件存储测试类"""

    def test_append_event(self, store):
        """测试事件追加：验证版本号自增和哈希计算"""
        event = Event(
            event_type="TaskStarted",
            actor=LlmConfig(provider="test", model="mock"),
            payload={"prompt": "test"},
        )
        saved = store.append(event)
        assert saved.version == 1
        assert saved.event_hash.startswith("sha256:")
        assert saved.created_at is not None

    def test_list_events(self, store):
        """测试事件列表：验证按版本升序返回"""
        e1 = store.append(Event(event_type="TaskStarted", actor=LlmConfig(), payload={"seq": 1}))
        e2 = store.append(Event(event_type="FindingReported", actor=LlmConfig(), payload={"seq": 2}))
        events = store.list_events()
        assert len(events) == 2
        assert events[0].version == 1
        assert events[1].version == 2

    def test_get_events_range(self, store):
        """测试事件范围查询：验证版本范围过滤"""
        for i in range(5):
            store.append(Event(event_type="Test", actor=LlmConfig(), payload={"i": i}))
        events = store.get_events(from_version=2, to_version=4)
        assert len(events) == 3
        assert events[0].version == 2
        assert events[-1].version == 4

    def test_snapshot(self, store):
        """测试快照保存和加载"""
        for i in range(3):
            store.append(Event(event_type="Test", actor=LlmConfig(), payload={"i": i}))
        store.save_snapshot(3, {"key": "value"}, "sha256:abc")
        snapshot = store.get_latest_snapshot()
        assert snapshot is not None
        assert snapshot.version == 3
        assert snapshot.state["key"] == "value"
        assert snapshot.merkle_root == "sha256:abc"

    def test_latest_synthesis(self, store):
        """测试获取最新的综合事件"""
        store.append(Event(event_type="TaskStarted", actor=LlmConfig(), payload={}))
        store.append(Event(event_type="SynthesisGenerated", actor=LlmConfig(), payload={"content": "v1"}))
        store.append(Event(event_type="SynthesisRestored", actor=LlmConfig(), payload={"content": "v2"}))
        latest = store.latest_synthesis()
        assert latest is not None
        assert latest.payload["content"] == "v2"
