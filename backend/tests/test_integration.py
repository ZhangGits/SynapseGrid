"""Integration tests — End-to-end flow validation

Covers full lifecycle:
1. Create task -> verify Merkle chain -> rollback -> resynthesize
2. Export audit package -> verify ZIP contents
3. Version list -> verify version increment
4. Rate limiting -> verify 429 response
5. Prompt length limit -> verify 413 response

Uses TestClient for network-free integration testing.
"""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Fresh TestClient per test."""
    return TestClient(app)


def _create_task(client: TestClient, prompt: str) -> dict:
    """Helper: POST /api/v1/tasks and return JSON body."""
    resp = client.post(
        "/api/v1/tasks",
        json={
            "user_id": "test_user",
            "prompt": prompt,
            "template": "general",
            "output_mode": "markdown",
            "llm": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
            "llm_research": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
            "llm_verification": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
            "llm_synthesis": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ------------------------------------------------------------------
# 1. Full lifecycle: create -> rollback -> resynthesize
# ------------------------------------------------------------------

def test_full_lifecycle(client: TestClient) -> None:
    """End-to-end: create task -> rollback -> resynthesize -> verify Merkle chain."""
    data = _create_task(client, "Integration test: full lifecycle")
    session_id = data["session_id"]
    original_md = data["markdown_content"]
    original_events = data["audit_metadata"]["event_count"]
    
    assert session_id.startswith("sess_")
    assert original_events >= 5
    assert data["audit_metadata"]["merkle_root"].startswith("sha256:")
    assert data["audit_metadata"]["content_signature"].startswith("hmac:")
    
    # Rollback first finding
    rollbackable = data["rollback_options"]["rollbackable_findings"]
    assert len(rollbackable) >= 1
    fid = rollbackable[0]
    
    rb = client.post(
        f"/api/v1/tasks/{session_id}/rollback",
        json={"finding_id": fid, "reason": "integration test"},
    )
    assert rb.status_code == 200, rb.text
    rolled = rb.json()
    
    # Markdown must change (state-based rebuild, not text filtering)
    assert rolled["markdown_content"] != original_md
    assert "Rollback Notice" in rolled["markdown_content"]
    assert rolled["audit_metadata"]["event_count"] >= original_events + 2
    assert fid not in rolled["rollback_options"]["rollbackable_findings"]
    
    # Resynthesize
    rs = client.post(f"/api/v1/tasks/{session_id}/resynthesize")
    assert rs.status_code == 200, rs.text
    resynth = rs.json()
    assert resynth["audit_metadata"]["event_count"] >= rolled["audit_metadata"]["event_count"] + 1
    assert resynth["session_id"] == session_id


# ------------------------------------------------------------------
# 2. Audit package export
# ------------------------------------------------------------------

def test_export_audit_package(client: TestClient) -> None:
    """Test audit package export: verify ZIP contents."""
    data = _create_task(client, "Integration test: audit export")
    sid = data["session_id"]
    
    resp = client.post(f"/api/v1/tasks/{sid}/export-audit")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    assert sid in resp.headers["content-disposition"]
    
    buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        assert "events.jsonl" in names
        assert "merkle_proof.json" in names
        assert "signature.sig" in names
        assert "report.md" in names
        
        events = [json.loads(line) for line in zf.read("events.jsonl").decode().strip().split("\n") if line]
        assert len(events) >= 5
        assert events[0]["event_type"] == "TaskStarted"
        
        proof = json.loads(zf.read("merkle_proof.json"))
        assert proof["merkle_root"].startswith("sha256:")
        assert proof["event_count"] == len(events)
        assert proof["session_id"] == sid
        
        sig = zf.read("signature.sig").decode()
        assert "session_id:" in sig
        assert "signature: hmac:" in sig
        
        report = zf.read("report.md").decode()
        assert "# synapsegrid_audit" in report
        assert "content_signature: hmac:" in report


# ------------------------------------------------------------------
# 3. Version list
# ------------------------------------------------------------------

def test_versions_endpoint(client: TestClient) -> None:
    """Test version list: create + rollback should produce 2 versions."""
    data = _create_task(client, "Integration test: versions")
    sid = data["session_id"]
    
    v1 = client.get(f"/api/v1/tasks/{sid}/versions").json()
    assert v1["session_id"] == sid
    assert len(v1["versions"]) == 1
    assert v1["versions"][0]["event_type"] == "SynthesisGenerated"
    
    fid = data["rollback_options"]["rollbackable_findings"][0]
    client.post(f"/api/v1/tasks/{sid}/rollback", json={"finding_id": fid, "reason": "version test"})
    
    v2 = client.get(f"/api/v1/tasks/{sid}/versions").json()
    assert len(v2["versions"]) == 2
    assert v2["versions"][1]["event_type"] == "SynthesisRestored"
    assert v2["versions"][1]["finding_count"] < v2["versions"][0]["finding_count"]


# ------------------------------------------------------------------
# 4. Rate limiting
# ------------------------------------------------------------------

def test_rate_limiting(client: TestClient) -> None:
    """Test rate limiting: send 15 rapid requests, expect some 429s."""
    codes = []
    for i in range(15):
        resp = client.post(
            "/api/v1/tasks",
            json={
                "user_id": "rate_test",
                "prompt": f"Rate limit test {i}",
                "template": "general",
                "output_mode": "markdown",
                "llm": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
                "llm_research": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
                "llm_verification": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
                "llm_synthesis": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
            },
        )
        codes.append(resp.status_code)
    
    assert 429 in codes, f"Expected some 429s, got: {codes}"


# ------------------------------------------------------------------
# 5. Prompt length limit
# ------------------------------------------------------------------

def test_prompt_length_limit(client: TestClient) -> None:
    """Test prompt length limit: >8000 chars should return 413."""
    resp = client.post(
        "/api/v1/tasks",
        json={
            "user_id": "len_test",
            "prompt": "A" * 8001,
            "template": "general",
            "output_mode": "markdown",
            "llm": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
            "llm_research": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
            "llm_verification": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
            "llm_synthesis": {"provider": "chatgpt", "model": "gpt-4o-mini", "api_key": ""},
        },
    )
    assert resp.status_code == 413
    assert "too long" in resp.json()["detail"].lower()


# ------------------------------------------------------------------
# 6. Error handling
# ------------------------------------------------------------------

def test_rollback_missing_session(client: TestClient) -> None:
    """Rollback on non-existent session returns 404."""
    resp = client.post(
        "/api/v1/tasks/nonexistent-sess/rollback",
        json={"finding_id": "f1", "reason": "test"},
    )
    assert resp.status_code == 404


def test_export_missing_session(client: TestClient) -> None:
    """Export on non-existent session returns 404."""
    resp = client.post("/api/v1/tasks/nonexistent-sess/export-audit")
    assert resp.status_code == 404


def test_versions_missing_session(client: TestClient) -> None:
    """Versions on non-existent session returns 404."""
    resp = client.get("/api/v1/tasks/nonexistent-sess/versions")
    assert resp.status_code == 404