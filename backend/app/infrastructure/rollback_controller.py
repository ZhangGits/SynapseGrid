"""回退控制器 — 处理分析要点的回退逻辑

v4.0 Phase 1: call ResearchAgent.rebuild() instead of SynthesisAgent.run()
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.session_manager import session_manager
from app.schemas.machine_wire import Event, LlmConfig
from app.services.post_processor import enrich

logger = logging.getLogger(__name__)


class RollbackError(Exception):
    pass


class RollbackController:

    def __init__(self, research_agent, synthesis_agent) -> None:
        self.research_agent = research_agent
        self.synthesis_agent = synthesis_agent

    async def execute(self, ctx, finding_id: str, reason: str) -> None:
        state = ctx.projection.dump()
        findings = state.get("findings", {})

        if finding_id not in findings:
            raise RollbackError("Finding not found")
        if findings[finding_id].get("rolled_back"):
            raise RollbackError("Already rolled back")

        rollback_ev = Event(
            event_type="FindingRolledBack",
            actor=findings[finding_id].get("agent", "rollback_controller"),
            payload={"finding_id": finding_id, "reason": reason},
            metadata={"finding_id": finding_id},
            semantic_digest=f"Rollback finding {finding_id}",
        )
        await session_manager.append_event(ctx, rollback_ev)

        state_after = ctx.projection.dump()
        all_findings = list(state_after.get("findings", {}).values())
        active_findings = [f for f in all_findings if not f.get("rolled_back")]

        events = ctx.event_store.list_events()

        task = state_after.get("task", {})
        output_mode = task.get("output_mode", "markdown")
        template = task.get("template", "general")
        prompt = task.get("prompt", "")

        llm_synthesis = LlmConfig()
        for e in reversed(events):
            if e.event_type in ("SynthesisGenerated", "MarkdownGenerated") and isinstance(e.actor, LlmConfig):
                llm_synthesis = e.actor
                break

        cred_map = state_after.get("credibility_assessments", {})

        if not active_findings:
            empty_md = f"# Report\n\n> **Rollback Notice**: Finding `{finding_id}` rolled back.\n"
            restore_ev = Event(
                event_type="MarkdownRestored",
                actor="rollback_controller",
                payload={"markdown_content": empty_md, "enriched_markdown": empty_md},
                metadata={"finding_id": finding_id},
            )
            await session_manager.append_event(ctx, restore_ev)
            return

        rebuilt_md = await self.research_agent.rebuild(
            prompt=prompt,
            template=template,
            rolled_back_id=finding_id,
            reason=reason,
            remaining_findings=active_findings,
            llm=llm_synthesis,
        )

        if output_mode == "markdown":
            assessments_list = list(cred_map.values()) if isinstance(cred_map, dict) else []
            relations_list = state_after.get("relations", [])
            enriched_md = enrich(rebuilt_md, assessments_list, relations_list)
            restore_ev = Event(
                event_type="MarkdownRestored",
                actor="rollback_controller",
                payload={
                    "markdown_content": rebuilt_md,
                    "enriched_markdown": enriched_md,
                    "rolled_back_finding": finding_id,
                },
                metadata={"finding_id": finding_id},
                semantic_digest=f"Rebuilt markdown (finding {finding_id} excluded)",
            )
        else:
            assessments_list = list(cred_map.values()) if isinstance(cred_map, dict) else []
            relations_list = state_after.get("relations", [])
            synth_result = await self.synthesis_agent.run(
                rebuilt_md, active_findings, assessments_list, relations_list,
                llm_synthesis, template,
            )
            enriched_md = synth_result.enriched_markdown or enrich(rebuilt_md, assessments_list, relations_list)
            restore_ev = Event(
                event_type="SynthesisRestored",
                actor="rollback_controller",
                payload={
                    "markdown_content": rebuilt_md,
                    "enriched_markdown": enriched_md,
                    "logic_graph": synth_result.logic_graph.model_dump(),
                    "node_map": synth_result.node_map,
                    "rolled_back_finding": finding_id,
                },
                metadata={"finding_id": finding_id},
                semantic_digest=f"Rebuilt canvas (finding {finding_id} excluded)",
            )

        await session_manager.append_event(ctx, restore_ev)
        logger.info("Rollback done sess=%s finding=%s", ctx.session_id, finding_id)