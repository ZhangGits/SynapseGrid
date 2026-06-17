"""任务编排器 — 协调 Research→Verification→Synthesis 三阶段流水线

核心职责：
1. 接收 TaskRequest，创建会话，启动三阶段 Agent 流水线
2. 管理事件追加（通过 session_manager.append_event）
3. 处理回退请求（RollbackController）
4. 构建 TaskResponse 返回给 API 层

v4.0 Phase 1 更新：
- Research.run() 返回 (raw_markdown, findings) 元组
- Verification 返回 (assessments, relations)
- 双路径分支：markdown 模式跳过 Synthesis，canvas 模式调用 Synthesis
- 回退调用 ResearchAgent.rebuild() 而非 SynthesisAgent.run()
- Markdown 模式生成 MarkdownGenerated 事件，Canvas 模式生成 SynthesisGenerated
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.agents.research import ResearchAgent
from app.agents.synthesis import SynthesisAgent
from app.agents.verification import VerificationAgent
from app.core.session_manager import session_manager
from app.infrastructure.rollback_controller import RollbackController
from pydantic import BaseModel

from app.schemas.api_response import (
    AuditMetadata,
    LineageData,
    RollbackOptions,
    TaskResponse,
)
from app.schemas.machine_wire import (
    CostRecord,
    CredibilityAssessment,
    Event,
    FindingRelation,
    LlmConfig,
    SynthesisResult,
    TaskRequest,
    LogicGraph,
)
from app.services.cost_tracker import CostTracker, MODEL_PRICING
from app.services.post_processor import with_audit_header, enrich

# SACP 协议相关导入
from app.schemas.agent_wire import AgentMessage, AgentMsgType, CompressedPayload
from app.services.toon_serializer import TOONSerializer

logger = logging.getLogger(__name__)


def _make_semantic_digest(event_type: str, payload: dict) -> str:
    """生成事件的语义摘要（一句话描述）"""
    if event_type == "TaskStarted":
        prompt = payload.get("prompt", "")[:40]
        return f"用户提交分析任务: '{prompt}...'"
    elif event_type == "FindingReported":
        f = payload.get("finding", {})
        return f"发现分析要点 {f.get('id', '?')}: {f.get('claim', '')[:40]}..."
    elif event_type == "CredibilityAssessed":
        a = payload.get("assessment", {})
        return f"评估 finding {a.get('finding_id', '?')} 可信度={a.get('overall_credibility', 0):.0%}"
    elif event_type == "RelationDetected":
        r = payload.get("relation", {})
        return f"发现关系 {r.get('relation_type', '?')}: {', '.join(r.get('between', []))}"
    elif event_type == "SynthesisGenerated":
        return f"生成综合报告 (canvas 模式)"
    elif event_type == "MarkdownGenerated":
        return f"生成 Markdown 报告"
    elif event_type == "FindingRolledBack":
        return f"回退 finding {payload.get('finding_id', '?')}: {payload.get('reason', '')[:30]}..."
    elif event_type == "SynthesisRestored":
        return f"回退后重新生成报告 (canvas)"
    elif event_type == "MarkdownRestored":
        return f"回退后重新生成 Markdown 报告"
    return f"{event_type} event"


class Orchestrator:
    """任务编排器 — 三阶段 Agent 流水线的中央协调器"""

    def __init__(self) -> None:
        self.research_agent = ResearchAgent()
        self.verification_agent = VerificationAgent()
        self.synthesis_agent = SynthesisAgent()
        self.rollback_controller = RollbackController(self.research_agent, self.synthesis_agent)
        self.cost_tracker = CostTracker()
        self._task_results: dict[str, TaskResponse] = {}

    # ------------------------------------------------------------------
    # 主任务入口（异步后台执行）
    # ------------------------------------------------------------------

    async def start_task(self, request: TaskRequest) -> str:
        """创建会话并启动后台任务，立即返回 session_id"""
        import asyncio
        ctx = session_manager.create_session(request.user_id)
        logger.info("Task started (async)  sess=%s  prompt_len=%s  template=%s  mode=%s",
                     ctx.session_id, len(request.prompt), request.template, request.output_mode)
        # 后台异步执行
        asyncio.create_task(self._run_task_async(ctx, request))
        return ctx.session_id

    async def _run_task_async(self, ctx, request: TaskRequest) -> None:
        """后台执行完整的三阶段 Agent 流水线，结果存储在 _task_results 中"""
        try:
            result = await self._run_task_core(ctx, request)
            self._task_results[ctx.session_id] = result
        except Exception as e:
            logger.exception("Task failed  sess=%s", ctx.session_id)
            # 存储错误结果
            self._task_results[ctx.session_id] = TaskResponse(
                session_id=ctx.session_id,
                markdown_content=f"# Error\n\nTask failed: {e}",
                audit_metadata=AuditMetadata(
                    session_id=ctx.session_id, merkle_root="", content_signature="",
                    findings=[], conflicts=[], cost_breakdown=[],
                    total_tokens=0, event_count=0, duration_seconds=0,
                ),
                lineage_data=LineageData(nodes=[], edges=[]),
                rollback_options=RollbackOptions(rollbackable_findings=[]),
            )

    async def get_task_result(self, session_id: str) -> TaskResponse | None:
        """获取已完成的任务结果"""
        return self._task_results.get(session_id)

    async def run_task(self, request: TaskRequest) -> TaskResponse:
        """同步执行完整的三阶段 Agent 流水线（兼容旧调用）

        v4.0 Phase 1 双路径：
        - markdown 模式：Research → Verification → MarkdownGenerated（跳过 Synthesis）
        - canvas 模式：Research → Verification → Synthesis → SynthesisGenerated
        """
        ctx = session_manager.create_session(request.user_id)
        return await self._run_task_core(ctx, request)

    async def _run_task_core(self, ctx, request: TaskRequest) -> TaskResponse:
        """执行完整的三阶段 Agent 流水线的核心逻辑"""
        logger.info("Task running  sess=%s  prompt_len=%s  template=%s  mode=%s",
                     ctx.session_id, len(request.prompt), request.template, request.output_mode)

        llm_research = request.llm_research or LlmConfig()
        llm_verification = request.llm_verification or LlmConfig()
        llm_synthesis = request.llm_synthesis or LlmConfig()

        # 1. TaskStarted 事件
        task_payload = {
            "prompt": request.prompt,
            "template": request.template,
            "output_mode": request.output_mode,
            "conversation_history": request.conversation_history,
        }
        task_event = Event(
            event_type="TaskStarted",
            actor=llm_research,
            payload=task_payload,
            metadata={"user_id": request.user_id, "agent_name": "research"},
            semantic_digest=_make_semantic_digest("TaskStarted", task_payload),
        )
        await session_manager.append_event(ctx, task_event)

        # 2. Research → (raw_markdown, findings)
        raw_markdown, findings = await self.research_agent.run(
            request.prompt, llm_research, request.template, request.conversation_history,
        )
        for finding in findings:
            ev = Event(
                event_type="FindingReported",
                actor=llm_research,
                payload={"finding": finding},
                metadata={"cost_usd": finding.get("cost_usd", 0.0), "agent_name": "research"},
                semantic_digest=_make_semantic_digest("FindingReported", {"finding": finding}),
            )
            await session_manager.append_event(ctx, ev)
        # Research 阶段完成标记
        await session_manager.append_event(ctx, Event(
            event_type="AgentExecutionCompleted",
            actor=llm_research,
            payload={"stage": "research", "finding_count": len(findings)},
            metadata={"agent_name": "research"},
            semantic_digest="Research 阶段完成",
        ))

        # 3. Verification → assessments + relations
        LIGHT_MODEL_MAP = {
            "chatgpt": "gpt-4o-mini", "deepseek": "deepseek-chat", "claude": "claude-3-haiku",
            "qwen": "qwen-turbo", "kimi": "moonshot-v1-8k", "gemini": "gemini-1.5-flash",
        }
        light_model = LIGHT_MODEL_MAP.get(llm_verification.provider, llm_verification.model)
        if llm_verification.model != light_model:
            llm_verification = LlmConfig(
                provider=llm_verification.provider, model=light_model,
                api_key=llm_verification.api_key, base_url=llm_verification.base_url,
            )
            logger.info("Model tiering: verification → %s", light_model)

        assessments, relations = await self.verification_agent.run(
            findings, llm_verification, request.template,
        )

        verif_cost = _estimate_verification_cost(llm_verification.model, len(findings))

        # 写入 CredibilityAssessed 事件
        for a in assessments:
            ev = Event(
                event_type="CredibilityAssessed",
                actor=llm_verification,
                payload={"assessment": a.model_dump()},
                metadata={"agent_name": "verification", "cost_usd": verif_cost},
                semantic_digest=f"评估 finding {a.finding_id} 可信度={a.overall_credibility:.0%}",
            )
            await session_manager.append_event(ctx, ev)

        # 写入 RelationDetected 事件
        for r in relations:
            ev = Event(
                event_type="RelationDetected",
                actor=llm_verification,
                payload={"relation": r.model_dump()},
                metadata={"agent_name": "verification", "cost_usd": verif_cost},
                semantic_digest=f"发现关系 {r.relation_type}: {', '.join(r.between)}",
            )
            await session_manager.append_event(ctx, ev)

        # Verification 阶段完成标记
        await session_manager.append_event(ctx, Event(
            event_type="AgentExecutionCompleted",
            actor=llm_verification,
            payload={"stage": "verification", "assessment_count": len(assessments), "relation_count": len(relations)},
            metadata={"agent_name": "verification"},
            semantic_digest="Verification 阶段完成",
        ))

        # 4. 根据 output_mode 分支
        if request.output_mode == "markdown":
            # Markdown 模式：PostProcessor.enrich() → MarkdownGenerated 事件
            enriched_markdown = enrich(raw_markdown, assessments, relations)
            md_ev = Event(
                event_type="MarkdownGenerated",
                actor=llm_synthesis,
                payload={"markdown_content": raw_markdown, "enriched_markdown": enriched_markdown},
                metadata={"agent_name": "post_processor"},
                semantic_digest="生成 Markdown 报告（跳过 Synthesis）",
            )
            await session_manager.append_event(ctx, md_ev)
        else:
            # Canvas 模式：SynthesisAgent.run() → SynthesisGenerated
            synth_result = await self.synthesis_agent.run(
                raw_markdown, findings, assessments, relations,
                llm_synthesis, request.template,
            )
            synth_cost = _estimate_synthesis_cost(llm_synthesis.model, len(findings))
            enriched_md = synth_result.enriched_markdown or enrich(raw_markdown, assessments, relations)
            synth_ev = Event(
                event_type="SynthesisGenerated",
                actor=llm_synthesis,
                payload={
                    "markdown_content": raw_markdown,
                    "enriched_markdown": enriched_md,
                    "logic_graph": synth_result.logic_graph.model_dump(),
                    "node_map": synth_result.node_map,
                },
                metadata={"agent_name": "synthesis", "cost_usd": synth_cost},
                semantic_digest="生成综合报告 (canvas 模式)",
            )
            await session_manager.append_event(ctx, synth_ev)

        # 5. 构建响应
        return self._build_response(ctx, request)

    # ------------------------------------------------------------------
    # 重新综合
    # ------------------------------------------------------------------

    async def resynthesize(self, ctx) -> TaskResponse:
        """基于当前会话中未回退的 findings 重新执行 Synthesis"""
        logger.info("Resynthesize  sess=%s", ctx.session_id)
        state = ctx.projection.dump()
        task_payload = state.get("task", {})

        all_findings = list(state.get("findings", {}).values())
        active_findings = [f for f in all_findings if not f.get("rolled_back")]

        if not active_findings:
            logger.warning("No active findings to synthesize")
            return self._build_response(ctx, TaskRequest(
                user_id=task_payload.get("user_id", "user001"),
                prompt=task_payload.get("prompt", ""),
                template=task_payload.get("template", "general"),
                output_mode=task_payload.get("output_mode", "markdown"),
            ))

        events = ctx.event_store.list_events()
        synth_ev = next((e for e in reversed(events)
                          if e.event_type == "SynthesisGenerated"), None)
        llm_synthesis = synth_ev.actor if synth_ev else LlmConfig()
        template = task_payload.get("template", "general")
        output_mode = task_payload.get("output_mode", "markdown")

        assessments_list = list(state.get("credibility_assessments", {}).values())
        relations_list = list(state.get("relations", []))

        # Find raw_markdown from first MarkdownGenerated or synthesis event
        raw_md = ""
        for e in events:
            if e.event_type in ("MarkdownGenerated", "SynthesisGenerated"):
                raw_md = e.payload.get("markdown_content", "")
                break

        synth_result = await self.synthesis_agent.run(
            raw_md, active_findings, assessments_list, relations_list,
            llm_synthesis, template,
        )
        enriched_md = synth_result.enriched_markdown or enrich(raw_md, assessments_list, relations_list)

        synth_ev = Event(
            event_type="SynthesisGenerated",
            actor=llm_synthesis,
            payload={
                "markdown_content": raw_md,
                "enriched_markdown": enriched_md,
                "logic_graph": synth_result.logic_graph.model_dump(),
                "node_map": synth_result.node_map,
            },
            metadata={"agent_name": "synthesis", "resynthesize": True},
        )
        await session_manager.append_event(ctx, synth_ev)

        return self._build_response(ctx, TaskRequest(
            user_id=task_payload.get("user_id", "user001"),
            prompt=task_payload.get("prompt", ""),
            template=template, output_mode=output_mode,
        ))

    # ------------------------------------------------------------------
    # 回退
    # ------------------------------------------------------------------

    async def rollback_finding(self, ctx, finding_id: str, reason: str) -> TaskResponse:
        """回退一个分析要点"""
        logger.info("Rollback  sess=%s  finding=%s  reason=%s", ctx.session_id, finding_id, reason)
        await self.rollback_controller.execute(ctx, finding_id, reason)
        return self._build_response(ctx, self._build_task_request(ctx))

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _build_task_request(self, ctx) -> TaskRequest:
        """从会话投影状态构建 TaskRequest"""
        task_payload = ctx.projection.state.get("task", {})
        return TaskRequest(
            user_id=task_payload.get("user_id", "user001"),
            prompt=task_payload.get("prompt", ""),
            template=task_payload.get("template", "general"),
            output_mode=task_payload.get("output_mode", "markdown"),
        )

    def _build_response(self, ctx, request: TaskRequest) -> TaskResponse:
        """从会话投影状态构建 TaskResponse"""
        state = ctx.projection.dump()
        events = ctx.event_store.list_events()
        root = ctx.projection.merkle_root

        # Find the latest relevant event
        synth_event_types = ("SynthesisGenerated", "SynthesisRestored",
                              "MarkdownGenerated", "MarkdownRestored")
        synthesis_ev = next(
            (e for e in reversed(events) if e.event_type in synth_event_types), None,
        )
        markdown = synthesis_ev.payload.get("markdown_content", "") if synthesis_ev else "# No report"
        enriched_md = synthesis_ev.payload.get("enriched_markdown", "") if synthesis_ev else ""

        _, sig = with_audit_header(markdown, ctx.session_id, root, len(events))

        findings = list(state.get("findings", {}).values())

        # Build cost records
        cost_records = []
        seen_agents: set[str] = set()
        for ev in events:
            agent_name = ev.metadata.get("agent_name", "unknown")
            cost_usd = ev.metadata.get("cost_usd", 0.0)
            model = "unknown"
            if isinstance(ev.actor, BaseModel):
                model = getattr(ev.actor, "model", "unknown")
            elif isinstance(ev.actor, str):
                model = ev.actor
            agent_key = f"{agent_name}_{model}"
            if agent_key not in seen_agents and cost_usd > 0:
                seen_agents.add(agent_key)
                tokens = _estimate_tokens_from_cost(cost_usd, model)
                cost_records.append(CostRecord(agent=agent_name, model=model, usd=cost_usd, tokens=tokens))
        if not cost_records:
            for f in findings:
                cu = f.get("cost_usd", 0)
                m = f.get("model", "unknown")
                a = f.get("agent", "unknown")
                if cu > 0:
                    cost_records.append(CostRecord(agent=a, model=m, usd=cu,
                        tokens=_estimate_tokens_from_cost(cu, m)))

        agent_traces = state.get("agent_traces", [])

        audit = AuditMetadata(
            session_id=ctx.session_id, merkle_root=root, content_signature=sig,
            findings=findings, conflicts=list(state.get("conflicts", {}).values()),
            cost_breakdown=cost_records, total_tokens=sum(r.tokens for r in cost_records),
            event_count=len(events), duration_seconds=0, agent_traces=agent_traces,
        )

        # Extract canvas_schema (LogicGraph) from synthesis event
        canvas_schema = None
        if synthesis_ev:
            lg_data = synthesis_ev.payload.get("logic_graph")
            if lg_data:
                try:
                    canvas_schema = LogicGraph(**lg_data)
                except Exception:
                    canvas_schema = state.get("canvas_schema")

        return TaskResponse(
            session_id=ctx.session_id,
            markdown_content=markdown,
            enriched_markdown=enriched_md,
            canvas_schema=canvas_schema,
            audit_metadata=audit,
            lineage_data=LineageData(**ctx.lineage.to_wire()),
            rollback_options=RollbackOptions(
                rollbackable_findings=[
                    f["id"] for f in findings if not f.get("rolled_back")
                ],
            ),
        )


def _get_avg_price(model: str) -> float:
    """获取模型的平均每 Token 价格"""
    pricing = MODEL_PRICING.get(model, {"input": 0.001, "output": 0.002})
    return (pricing["input"] + pricing["output"]) / 2


def _estimate_verification_cost(model: str, finding_count: int) -> float:
    """估算 Verification Agent 的调用成本"""
    if finding_count <= 0:
        return 0.0
    avg_price = _get_avg_price(model) / 1000
    return round((finding_count * 200 + 300) * avg_price, 6)


def _estimate_synthesis_cost(model: str, finding_count: int) -> float:
    """估算 Synthesis Agent 的调用成本"""
    if finding_count <= 0:
        return 0.0
    avg_price = _get_avg_price(model) / 1000
    return round((finding_count * 300 + 2000) * avg_price, 6)


def _estimate_tokens_from_cost(cost_usd: float, model: str) -> int:
    """根据费用和模型反推 Token 数"""
    if cost_usd <= 0:
        return 0
    avg_price = _get_avg_price(model) / 1000
    if avg_price <= 0:
        return 0
    return max(1, int(cost_usd / avg_price))


orchestrator = Orchestrator()
