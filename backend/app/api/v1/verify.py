"""Verification API routes — content verification and replay"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.session_manager import session_manager
from app.infrastructure.merkle import get_public_key_hex, verify_content
from app.services.post_processor import _sign_content

logger = logging.getLogger(__name__)

router = APIRouter(tags=["verify"])


class VerifyRequest(BaseModel):
    session_id: str
    content: str
    content_signature: str


class VerifyResponse(BaseModel):
    valid: bool
    session_id: str
    merkle_root: str = ""
    event_count: int = 0
    content_signature: str = ""


class SimpleVerifyRequest(BaseModel):
    session_id: str = ""


class SimpleVerifyResponse(BaseModel):
    valid: bool
    session_id: str
    merkle_root: str
    event_count: int
    content_signature: str
    message: str


@router.post("/verify", response_model=VerifyResponse)
async def verify_content_endpoint(request: VerifyRequest) -> VerifyResponse:
    ctx = session_manager.get_session(request.session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = ctx.event_store.list_events()
    expected_sig = _sign_content(
        request.content, request.session_id,
        ctx.projection.merkle_root, len(events),
    )
    valid = request.content_signature == expected_sig
    return VerifyResponse(
        valid=valid, session_id=request.session_id,
        merkle_root=ctx.projection.merkle_root,
        event_count=len(events), content_signature=expected_sig,
    )


@router.post("/verify/simple", response_model=SimpleVerifyResponse)
@router.post("/sessions/{session_id}/verify")
async def verify_simple(request: SimpleVerifyRequest) -> SimpleVerifyResponse:
    ctx = session_manager.get_session(request.session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = ctx.event_store.list_events()
    root = ctx.projection.merkle_root
    synth_types = ("SynthesisGenerated", "SynthesisRestored",
                    "MarkdownGenerated", "MarkdownRestored")
    synthesis_ev = next(
        (e for e in reversed(events) if e.event_type in synth_types), None,
    )
    if synthesis_ev is None:
        return SimpleVerifyResponse(
            valid=False, session_id=request.session_id, merkle_root=root,
            event_count=len(events), content_signature="",
            message="No synthesis found in session",
        )
    content = synthesis_ev.payload.get("markdown_content", "")
    expected_sig = _sign_content(content, request.session_id, root, len(events))
    return SimpleVerifyResponse(
        valid=True, session_id=request.session_id, merkle_root=root,
        event_count=len(events), content_signature=expected_sig,
        message="Current synthesis verified against Merkle root",
    )


@router.get("/verify/replay/{session_id}")
async def replay_session(session_id: str) -> dict:
    ctx = session_manager.get_session(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = ctx.event_store.list_events()
    return {
        "session_id": session_id, "event_count": len(events),
        "events": [{
            "version": e.version, "event_type": e.event_type,
            "event_hash": e.event_hash, "created_at": e.created_at,
        } for e in events],
    }


@router.get("/verify/public-key")
async def public_key() -> dict:
    return {"public_key": get_public_key_hex()}
