"""后处理器 — 审计头添加与内容签名

负责：
1. 在最终 Markdown 内容前添加 YAML 审计头
2. 使用 HMAC 对内容进行签名
3. 提供 with_audit_header 函数供编排器和 replay 端点使用
4. 提供 enrich() 函数进行 provenance 包裹和可信度摘要注入
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

HMAC_KEY = os.environ.get("SYNAPSEGRID_HMAC_KEY", "").encode("utf-8")


def with_audit_header(markdown, session_id, merkle_root, event_count):
    """在 Markdown 内容前添加 YAML 审计头并计算内容签名"""
    sig = _sign_content(markdown, session_id, merkle_root, event_count)
    header = (
        "---\n"
        "# synapsegrid_audit\n"
        f"session_id: {session_id}\n"
        f"merkle_root: {merkle_root}\n"
        f"event_count: {event_count}\n"
        f"content_signature: {sig}\n"
        "---\n\n"
    )
    return header + markdown, sig


def enrich(raw_markdown, credibility_assessments, relations):
    """轻量级 Markdown 增强，纯文本操作，不调用 LLM"""
    cred_map = {}
    for a in credibility_assessments:
        fid = a.finding_id if hasattr(a, 'finding_id') else a.get("finding_id", "")
        ov = a.overall_credibility if hasattr(a, 'overall_credibility') else a.get("overall_credibility", 0.5)
        cred_map[fid] = ov

    def wrap_provenance(match):
        fid = match.group(1)
        conf = match.group(2)
        c = match.group(3)
        cr = cred_map.get(fid, float(conf))
        return '<provenance finding="{}" credibility="{:.2f}"><finding id="{}" confidence="{}">{}</finding></provenance>'.format(fid, cr, fid, conf, c)

    pattern = r'<finding\s+id="([^"]+)"\s+confidence="([^"]+)"\s*>(.*?)</finding>'
    enriched = re.sub(pattern, wrap_provenance, raw_markdown, flags=re.DOTALL)

    if cred_map:
        lines = ["> **Credibility Summary**\n"]
        for fid, cr in sorted(cred_map.items()):
            emoji = "GREEN" if cr >= 0.8 else "YELLOW" if cr >= 0.6 else "RED"
            lines.append(f"> {emoji} **{fid}**: {cr:.0%}")
        block = "\n".join(lines) + "\n\n"
        h1 = re.search(r'^# .*$', enriched, re.MULTILINE)
        if h1:
            pos = h1.end()
            enriched = enriched[:pos] + "\n\n" + block + enriched[pos:]
        else:
            enriched = block + enriched

    for r in relations:
        rt = r.relation_type if hasattr(r, 'relation_type') else r.get("relation_type", "")
        bw = r.between if hasattr(r, 'between') else r.get("between", [])
        desc = r.description if hasattr(r, 'description') else r.get("description", "")
        if rt == "perspective_difference":
            hint = f"\n\n[Perspective] {desc} (findings: {', '.join(bw)})\n"
        elif rt == "tension":
            hint = f"\n\n[WARNING Tension] {desc} (findings: {', '.join(bw)})\n"
        elif rt == "genuine_contradiction":
            hint = f"\n\n[ALERT Contradiction] {desc} (findings: {', '.join(bw)})\n"
        else:
            continue
        enriched += hint

    return enriched


def _sign_content(markdown, session_id, merkle_root, event_count):
    """使用 HMAC-SHA256 对内容进行签名"""
    msg = f"{session_id}|{merkle_root}|{event_count}|{markdown}".encode("utf-8")
    digest = hmac.new(HMAC_KEY, msg, hashlib.sha256).hexdigest()
    return f"hmac:{digest}"
