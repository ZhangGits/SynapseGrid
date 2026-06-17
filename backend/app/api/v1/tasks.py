"""Task API routes — create, rollback, resynthesize, versions, export"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.orchestrator import orchestrator
from app.core.session_manager import session_manager
from app.schemas.api_response import TaskResponse, AuditMetadata, LineageData, RollbackOptions
from app.schemas.machine_wire import RollbackRequest, TaskRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


class VersionInfo(BaseModel):
    version: int
    event_type: str
    created_at: str
    summary: str
    finding_count: int


class VersionsResponse(BaseModel):
    session_id: str
    versions: list[VersionInfo]


@router.post("/tasks")
async def create_task(request: TaskRequest) -> dict:
    """创建异步任务，立即返回 session_id"""
    logger.info("POST /tasks  prompt_len=%s  template=%s  mode=%s", len(request.prompt), request.template, request.output_mode)
    session_id = await orchestrator.start_task(request)
    return {"session_id": session_id, "status": "processing"}


@router.get("/tasks/{session_id}/result", response_model=TaskResponse | None)
async def get_task_result(session_id: str) -> TaskResponse | None:
    """获取已完成的任务结果"""
    return await orchestrator.get_task_result(session_id)


@router.get("/tasks/{session_id}/progress")
async def get_task_progress(session_id: str) -> dict:
    """获取任务当前进度（已完成的阶段列表）"""
    ctx = session_manager.get_session(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    state = ctx.projection.dump()
    events = ctx.event_store.list_events()
    completed_stages = state.get("completed_stages", [])
    # 检查是否已有结果
    has_result = session_id in orchestrator._task_results
    return {
        "session_id": session_id,
        "completed_stages": completed_stages,
        "event_count": len(events),
        "has_result": has_result,
    }


@router.post("/sessions/{session_id}/rollback", response_model=TaskResponse)
@router.post("/tasks/{session_id}/rollback", response_model=TaskResponse)
async def rollback_finding(session_id: str, request: RollbackRequest) -> TaskResponse:
    ctx = session_manager.get_session(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return await orchestrator.rollback_finding(ctx, request.finding_id, request.reason)
    except Exception:
        state = ctx.projection.dump()
        findings = list(state.get("findings", {}).values())
        return TaskResponse(
            session_id=session_id, markdown_content="",
            audit_metadata=AuditMetadata(session_id=session_id, findings=findings),
            lineage_data=LineageData(**ctx.lineage.to_wire()),
            rollback_options=RollbackOptions(
                rollbackable_findings=[f["id"] for f in findings if not f.get("rolled_back")]
            ),
        )


@router.post("/sessions/{session_id}/close")
async def close_session(session_id: str) -> dict:
    ctx = session_manager.get_session(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await session_manager.close_session(session_id, schedule=True)
    return {"status": "scheduled_for_cleanup", "session_id": session_id}


@router.post("/tasks/{session_id}/resynthesize", response_model=TaskResponse)
async def resynthesize(session_id: str) -> TaskResponse:
    ctx = session_manager.get_session(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return await orchestrator.resynthesize(ctx)


@router.get("/tasks/{session_id}/events")
async def get_events(session_id: str) -> dict:
    ctx = session_manager.get_session(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = ctx.event_store.list_events()
    return {
        "session_id": session_id, "event_count": len(events),
        "merkle_root": ctx.projection.merkle_root,
        "events": [{
            "version": ev.version, "event_type": ev.event_type,
            "payload": ev.payload, "metadata": ev.metadata,
            "event_hash": ev.event_hash, "created_at": ev.created_at,
        } for ev in events],
    }


@router.get("/tasks/{session_id}/versions", response_model=VersionsResponse)
async def get_versions(session_id: str) -> VersionsResponse:
    ctx = session_manager.get_session(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = ctx.event_store.list_events()
    versions: list[VersionInfo] = []
    synth_types = ("SynthesisGenerated", "SynthesisRestored", "MarkdownGenerated", "MarkdownRestored")
    for ev in events:
        if ev.event_type in synth_types:
            payload = ev.payload or {}
            md = payload.get("markdown_content", "")
            summary = md.replace("\n", " ").strip()[:80] + "..." if len(md) > 80 else md
            before = events[:events.index(ev) + 1]
            finding_count = (
                len([e for e in before if e.event_type == "FindingReported"])
                - len([e for e in before if e.event_type == "FindingRolledBack"])
            )
            versions.append(VersionInfo(
                version=ev.version, event_type=ev.event_type,
                created_at=ev.created_at or "", summary=summary,
                finding_count=max(0, finding_count),
            ))
    return VersionsResponse(session_id=session_id, versions=versions)


@router.post("/tasks/{session_id}/export-audit")
async def export_audit(session_id: str) -> StreamingResponse:
    from app.services.post_processor import with_audit_header
    ctx = session_manager.get_session(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = ctx.event_store.list_events()
    merkle_root = ctx.projection.merkle_root

    events_jsonl = "\n".join(
        json.dumps({
            "version": ev.version, "event_type": ev.event_type,
            "payload": ev.payload, "metadata": ev.metadata,
            "event_hash": ev.event_hash, "created_at": ev.created_at,
        }, ensure_ascii=False)
        for ev in events
    )
    merkle_proof = json.dumps({
        "merkle_root": merkle_root, "event_count": len(events),
        "session_id": session_id,
    }, indent=2, ensure_ascii=False)
    synth_types = ("SynthesisGenerated", "SynthesisRestored", "MarkdownGenerated", "MarkdownRestored")
    synthesis_ev = next((e for e in reversed(events) if e.event_type in synth_types), None)
    md = synthesis_ev.payload.get("markdown_content", "# No report") if synthesis_ev else "# No report"
    report_md, sig = with_audit_header(md, session_id, merkle_root, len(events))
    sig_content = f"session_id: {session_id}\nmerkle_root: {merkle_root}\nevent_count: {len(events)}\nsignature: {sig}\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("events.jsonl", events_jsonl)
        zf.writestr("merkle_proof.json", merkle_proof)
        zf.writestr("signature.sig", sig_content)
        zf.writestr("report.md", report_md)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={session_id}_audit.zip"},
    )
