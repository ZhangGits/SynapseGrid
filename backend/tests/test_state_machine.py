"""状态机单元测试

测试 SessionStateProjection 的事件投影和状态重建功能。
"""

from __future__ import annotations

from app.core.state_machine import SessionStateProjection
from app.schemas.machine_wire import Event, LlmConfig


class TestStateProjection:
    """状态投影测试类"""

    def test_task_started(self):
        """测试 TaskStarted 事件投影"""
        proj = SessionStateProjection()
        event = Event(
            event_type="TaskStarted",
            actor=LlmConfig(),
            payload={"prompt": "test", "template": "general"},
        )
        event.version = 1
        event.event_hash = "sha256:test"
        proj.apply(event)
        assert proj.state["task"]["prompt"] == "test"
        assert proj.current_version == 1

    def test_finding_reported(self):
        """测试 FindingReported 事件投影"""
        proj = SessionStateProjection()
        event = Event(
            event_type="FindingReported",
            actor=LlmConfig(),
            payload={"finding": {"id": "f1", "claim": "test finding"}},
        )
        event.version = 1
        event.event_hash = "sha256:test"
        proj.apply(event)
        assert "f1" in proj.state["findings"]
        assert proj.state["findings"]["f1"]["claim"] == "test finding"

    def test_finding_validated(self):
        """测试 FindingValidated 事件投影"""
        proj = SessionStateProjection()
        # 先添加 finding
        e1 = Event(
            event_type="FindingReported",
            actor=LlmConfig(),
            payload={"finding": {"id": "f1", "claim": "test"}},
        )
        e1.version = 1
        e1.event_hash = "sha256:a"
        proj.apply(e1)
        # 再验证
        e2 = Event(
            event_type="FindingValidated",
            actor=LlmConfig(),
            payload={"finding_id": "f1"},
        )
        e2.version = 2
        e2.event_hash = "sha256:b"
        proj.apply(e2)
        assert proj.state["findings"]["f1"]["validated"] is True

    def test_rebuild(self):
        """测试状态重建"""
        proj = SessionStateProjection()
        events = [
            Event(
                event_type="TaskStarted", actor=LlmConfig(),
                payload={"prompt": "test"}, version=1, event_hash="sha256:a",
            ),
            Event(
                event_type="FindingReported", actor=LlmConfig(),
                payload={"finding": {"id": "f1", "claim": "test"}},
                version=2, event_hash="sha256:b",
            ),
        ]
        proj.rebuild(events)
        assert proj.state["task"]["prompt"] == "test"
        assert "f1" in proj.state["findings"]
        assert proj.current_version == 2

    def test_credibility_assessed(self):
        """测试 CredibilityAssessed 事件投影（Phase 1 v4.0）"""
        proj = SessionStateProjection()
        # 先添加 finding
        e1 = Event(
            event_type="FindingReported",
            actor=LlmConfig(),
            payload={"finding": {"id": "f1", "claim": "test finding"}},
        )
        e1.version = 1
        e1.event_hash = "sha256:a"
        proj.apply(e1)
        # 再评估可信度
        e2 = Event(
            event_type="CredibilityAssessed",
            actor=LlmConfig(),
            payload={
                "assessment": {
                    "finding_id": "f1",
                    "evidence_strength": 0.85,
                    "source_reliability": 0.80,
                    "reasoning_soundness": 0.90,
                    "data_consistency": 0.88,
                    "overall_credibility": 0.86,
                    "assessment": "论据充分，推理严密",
                    "concerns": [],
                    "suggestions": [],
                }
            },
        )
        e2.version = 2
        e2.event_hash = "sha256:b"
        proj.apply(e2)
        assert "f1" in proj.state["credibility_assessments"]
        assessment = proj.state["credibility_assessments"]["f1"]
        assert assessment["evidence_strength"] == 0.85
        assert assessment["overall_credibility"] == 0.86
        # 同时应该合并到 finding 中
        assert proj.state["findings"]["f1"]["credibility"] == assessment

    def test_relation_detected(self):
        """测试 RelationDetected 事件投影（Phase 1 v4.0）"""
        proj = SessionStateProjection()
        e1 = Event(
            event_type="RelationDetected",
            actor=LlmConfig(),
            payload={
                "relation": {
                    "between": ["f1", "f2"],
                    "relation_type": "perspective_difference",
                    "description": "从不同维度分析",
                }
            },
        )
        e1.version = 1
        e1.event_hash = "sha256:a"
        proj.apply(e1)
        assert len(proj.state["relations"]) == 1
        assert proj.state["relations"][0]["relation_type"] == "perspective_difference"
        assert proj.state["relations"][0]["between"] == ["f1", "f2"]

    def test_markdown_generated(self):
        """测试 MarkdownGenerated 事件投影（Phase 1 v4.0）"""
        proj = SessionStateProjection()
        e1 = Event(
            event_type="MarkdownGenerated",
            actor=LlmConfig(),
            payload={"markdown": "# Report\n\nSome content"},
        )
        e1.version = 1
        e1.event_hash = "sha256:a"
        proj.apply(e1)
        assert proj.state["synthesis"] == {"markdown": "# Report\n\nSome content"}
        assert proj.state["canvas_schema"] is None

    def test_markdown_restored(self):
        """测试 MarkdownRestored 事件投影（Phase 1 v4.0）"""
        proj = SessionStateProjection()
        e1 = Event(
            event_type="MarkdownRestored",
            actor=LlmConfig(),
            payload={"markdown": "# Restored\n\nUpdated content"},
        )
        e1.version = 1
        e1.event_hash = "sha256:a"
        proj.apply(e1)
        assert proj.state["synthesis_restored"] == {"markdown": "# Restored\n\nUpdated content"}
        assert proj.state["canvas_schema"] is None

    def test_finding_rolled_back_updates_credibility(self):
        """测试回退 finding 时同步更新 credibility_assessments（Phase 1 v4.0）"""
        proj = SessionStateProjection()
        # 添加 finding
        e1 = Event(
            event_type="FindingReported",
            actor=LlmConfig(),
            payload={"finding": {"id": "f1", "claim": "test"}},
        )
        e1.version = 1
        e1.event_hash = "sha256:a"
        proj.apply(e1)
        # 添加可信度评估
        e2 = Event(
            event_type="CredibilityAssessed",
            actor=LlmConfig(),
            payload={
                "assessment": {
                    "finding_id": "f1",
                    "evidence_strength": 0.85,
                    "source_reliability": 0.80,
                    "reasoning_soundness": 0.90,
                    "data_consistency": 0.88,
                    "overall_credibility": 0.86,
                    "assessment": "good",
                    "concerns": [],
                    "suggestions": [],
                }
            },
        )
        e2.version = 2
        e2.event_hash = "sha256:b"
        proj.apply(e2)
        # 回退
        e3 = Event(
            event_type="FindingRolledBack",
            actor=LlmConfig(),
            payload={"finding_id": "f1", "reason": "test rollback"},
        )
        e3.version = 3
        e3.event_hash = "sha256:c"
        proj.apply(e3)
        assert "f1" in proj.state["rolled_back_findings"]
        assert proj.state["findings"]["f1"]["rolled_back"] is True
        assert proj.state["credibility_assessments"]["f1"]["rolled_back"] is True
