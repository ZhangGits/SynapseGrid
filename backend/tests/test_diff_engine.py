"""Diff 引擎测试"""
import pytest
from app.services.diff_engine import FindingDiffEngine


def test_compute_diff_added():
    old = [{"id": "f1", "claim": "A", "confidence": 0.9}]
    new = [{"id": "f1", "claim": "A", "confidence": 0.9}, {"id": "f2", "claim": "B", "confidence": 0.8}]
    diff = FindingDiffEngine.compute_diff(old, new)
    assert diff["added"] == [{"id": "f2", "claim": "B", "confidence": 0.8}]
    assert diff["unchanged"] == ["f1"]


def test_compute_diff_modified():
    old = [{"id": "f1", "claim": "A", "confidence": 0.9}]
    new = [{"id": "f1", "claim": "A updated", "confidence": 0.9}]
    diff = FindingDiffEngine.compute_diff(old, new)
    assert diff["modified"] == [{"id": "f1", "claim": "A updated", "confidence": 0.9}]
    assert diff["unchanged"] == []


def test_compute_diff_removed():
    old = [{"id": "f1", "claim": "A", "confidence": 0.9}, {"id": "f2", "claim": "B", "confidence": 0.8}]
    new = [{"id": "f1", "claim": "A", "confidence": 0.9}]
    diff = FindingDiffEngine.compute_diff(old, new)
    assert diff["removed"] == ["f2"]
    assert diff["unchanged"] == ["f1"]


def test_diff_to_toon_format():
    """Diff TOON 格式包含正确结构"""
    old = [{"id": "f1", "claim": "A", "confidence": 0.9}]
    new = [{"id": "f1", "claim": "A", "confidence": 0.9}, {"id": "f2", "claim": "B", "confidence": 0.8}]
    diff = FindingDiffEngine.compute_diff(old, new)
    toon = FindingDiffEngine.diff_to_toon(diff)
    assert "diff{" in toon
    assert "added[1]:" in toon
    assert "unchanged[1]:" in toon
    assert "f2" in toon
    assert "f1" in toon


def test_apply_diff():
    base = [{"id": "f1", "claim": "A", "confidence": 0.9}]
    diff = {
        "added": [{"id": "f2", "claim": "B", "confidence": 0.8}],
        "modified": [],
        "unchanged": ["f1"],
        "removed": [],
    }
    result = FindingDiffEngine.apply_diff(base, diff)
    assert len(result) == 2
    ids = [f["id"] for f in result]
    assert "f1" in ids and "f2" in ids


def test_estimate_savings():
    """大量 unchanged finding 时 diff 节省显著"""
    # 使用大量数据才能体现 diff 节省
    old = [{"id": f"f{i}", "claim": f"Claim {i}", "confidence": 0.9} for i in range(10)]
    new = [{"id": f"f{i}", "claim": f"Claim {i}", "confidence": 0.9} for i in range(10)]
    new.append({"id": "f_new", "claim": "New finding", "confidence": 0.8})
    stats = FindingDiffEngine.estimate_savings(old, new)
    # 大量 unchanged 时 diff 应该比完整列表小
    assert stats["savings_vs_full_toon_percent"] > 0
