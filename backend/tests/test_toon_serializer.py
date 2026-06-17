"""TOON 序列化器测试"""
import pytest
from app.services.toon_serializer import TOONSerializer


def test_findings_to_toon_basic():
    findings = [
        {"id": "f1", "claim": "NEV +45%", "confidence": 0.92, "evidence": "MIIT", "source": "report"},
        {"id": "f2", "claim": "CATL $80/kWh", "confidence": 0.85},
    ]
    toon = TOONSerializer.findings_to_toon(findings)
    assert "findings[2]{id,claim,confidence,evidence,source}:" in toon
    assert "f1,NEV +45%,0.92,MIIT,report" in toon
    assert "f2,CATL $80/kWh,0.85,," in toon


def test_toon_to_findings_roundtrip():
    findings = [{"id": "f1", "claim": "Test", "confidence": 0.9}]
    toon = TOONSerializer.findings_to_toon(findings)
    back = TOONSerializer.toon_to_findings(toon)
    assert len(back) == 1
    assert back[0]["id"] == "f1"
    assert back[0]["claim"] == "Test"
    assert back[0]["confidence"] == 0.9


def test_compare_size():
    findings = [{"id": f"f{i}", "claim": f"Claim {i}", "confidence": 0.9} for i in range(5)]
    stats = TOONSerializer.compare_size(findings)
    assert stats["savings_percent"] > 0
    assert stats["json_chars"] > stats["toon_chars"]


def test_validation_result_to_toon():
    validated = ["f1", "f2"]
    conflicts = [{"id": "c1", "between": ["f1", "f2"], "severity": "medium", "reason": "test"}]
    toon = TOONSerializer.validation_result_to_toon(validated, conflicts)
    assert "validated[2]:" in toon
    assert "conflicts[1]{id,between,severity,reason}:" in toon
    assert "c1,f1|f2,medium,test" in toon