"""内存状态投影模块 — 从追加事件存储重建应用状态

关键不变性：
  1. 先持久化：事件先写入 SQLite 再投影到内存
  2. 每个版本都有 Merkle 跟踪，用于快照验证
  3. 通过 get_state_at(version) 实现快照加速的部分重放
  4. 通过 rebuild(events) 实现崩溃恢复
"""

from __future__ import annotations

import logging
from copy import deepcopy

from pydantic import BaseModel

from app.infrastructure.merkle import MerkleTree
from app.schemas.machine_wire import Event

logger = logging.getLogger(__name__)


class SessionStateProjection:
    """会话状态投影：将事件流投影为可查询的内存状态

    维护 findings、conflicts、credibility_assessments、costs 等状态的当前视图，
    支持快照加速的历史状态查询。
    """

    def __init__(self):
        """初始化空状态和 Merkle 树"""
        self.state = {
            "task": None,
            "findings": {},
            "conflicts": {},
            "credibility_assessments": {},
            "relations": [],
            "rolled_back_findings": [],
            "costs": [],
            "synthesis": None,
            "agent_traces": [],
            "canvas_schema": None,
        }
        self.merkle_tree = MerkleTree()
        self.current_version = 0
        self._state_dirty = False

    def apply(self, event):
        """应用一个事件到当前状态

        将事件投影到 state 字典，并更新 Merkle 树和版本号。

        Args:
            event: 要应用的事件对象

        Raises:
            Exception: 投影失败时抛出，并将 _state_dirty 标记为 True
        """
        try:
            _project(event, self.state)
            self.merkle_tree.append(event.event_hash)
            self.current_version = event.version
            self._state_dirty = False
        except Exception:
            logger.exception("Projection failed v=%s", event.version)
            self._state_dirty = True
            raise

    def rebuild(self, events):
        """从事件列表完全重建状态

        清空当前状态和 Merkle 树，然后按顺序应用所有事件。

        Args:
            events: 事件对象列表，按版本升序排列
        """
        self.state = {
            "task": None,
            "findings": {},
            "conflicts": {},
            "credibility_assessments": {},
            "relations": [],
            "rolled_back_findings": [],
            "costs": [],
            "synthesis": None,
            "agent_traces": [],
            "canvas_schema": None,
        }
        self.merkle_tree = MerkleTree()
        for event in events:
            _project(event, self.state)
            self.merkle_tree.append(event.event_hash)
        self.current_version = events[-1].version if events else 0
        self._state_dirty = False

    def get_state_at(self, target_version, event_store):
        """获取指定版本的历史状态（快照加速）

        从最近的快照开始，然后重放快照之后到目标版本之间的事件。

        Args:
            target_version: 目标版本号
            event_store: 事件存储对象，用于获取快照和事件

        Returns:
            目标版本的深拷贝状态字典
        """
        snapshot = event_store.get_latest_snapshot(max_version=target_version)
        if snapshot is not None:
            state = deepcopy(snapshot.state)
            start_version = snapshot.version
        else:
            state = {
                "task": None,
                "findings": {},
                "conflicts": {},
                "credibility_assessments": {},
                "relations": [],
                "rolled_back_findings": [],
                "costs": [],
                "synthesis": None,
                "agent_traces": [],
            }
            start_version = 0
        tail_events = event_store.get_events(
            from_version=start_version + 1,
            to_version=target_version,
        )
        for event in tail_events:
            if event.version > target_version:
                break
            _project(event, state)
        return deepcopy(state)

    def dump(self):
        """返回当前状态的深拷贝"""
        return deepcopy(self.state)

    @property
    def merkle_root(self):
        """当前 Merkle 树的根哈希"""
        return self.merkle_tree.root_hash

    @property
    def is_dirty(self):
        """状态是否脏（上次 apply 失败）"""
        return self._state_dirty


def _project(event, state):
    """将单个事件投影到状态字典中

    根据事件类型更新状态的不同部分：
    - TaskStarted: 存储任务信息
    - FindingReported: 添加分析要点
    - FindingValidated: 标记分析要点已验证（兼容 v3.1）
    - FindingRolledBack: 标记分析要点已回退
    - AggregationCompleted: 存储聚合结果
    - ConflictDetected: 添加冲突（兼容 v3.1）
    - CredibilityAssessed: 存储可信度评估（v4.0）
    - RelationDetected: 存储 finding 间关系（v4.0）
    - SynthesisGenerated: 存储综合结果
    - SynthesisRestored: 存储恢复的综合结果
    - MarkdownGenerated: 存储 Markdown 模式结果（v4.0，无 Synthesis）
    - MarkdownRestored: 存储 Markdown 模式回退结果（v4.0）
    - CanvasUpdated: 更新画布模式
    - AgentExecution: 累积执行追踪
    - 同时从 metadata 中提取成本信息
    """
    if event.event_type == "TaskStarted":
        state["task"] = event.payload
    elif event.event_type == "FindingReported":
        finding = event.payload["finding"]
        state["findings"][finding["id"]] = finding
    elif event.event_type == "FindingValidated":
        # v3.1 兼容：标记 finding 已验证
        fid = event.payload["finding_id"]
        if fid in state["findings"]:
            state["findings"][fid]["validated"] = True
    elif event.event_type == "FindingRolledBack":
        fid = event.payload["finding_id"]
        state["rolled_back_findings"].append(fid)
        if fid in state["findings"]:
            state["findings"][fid]["rolled_back"] = True
        # 同步更新 credibility_assessments
        if fid in state["credibility_assessments"]:
            state["credibility_assessments"][fid]["rolled_back"] = True
    elif event.event_type == "AggregationCompleted":
        state["aggregation"] = event.payload
    elif event.event_type == "ConflictDetected":
        # v3.1 兼容：存储冲突
        conflict = event.payload["conflict"]
        state["conflicts"][conflict["id"]] = conflict
    elif event.event_type == "CredibilityAssessed":
        # v4.0：存储可信度评估
        assessment = event.payload["assessment"]
        fid = assessment.get("finding_id", "")
        state["credibility_assessments"][fid] = assessment
        # 同时将可信度信息合并到 finding 中
        if fid in state["findings"]:
            state["findings"][fid]["credibility"] = assessment
    elif event.event_type == "RelationDetected":
        # v4.0：存储 finding 间关系
        relation = event.payload["relation"]
        state.setdefault("relations", []).append(relation)
    elif event.event_type == "SynthesisGenerated":
        state["synthesis"] = event.payload
        # 如果 synthesis payload 中有 canvas_schema，提取出来
        if "canvas_schema" in event.payload:
            state["canvas_schema"] = event.payload["canvas_schema"]
    elif event.event_type == "SynthesisRestored":
        state["synthesis_restored"] = event.payload
        # 如果 SynthesisRestored payload 中有 canvas_schema，提取出来
        if "canvas_schema" in event.payload:
            state["canvas_schema"] = event.payload["canvas_schema"]
    elif event.event_type == "MarkdownGenerated":
        # v4.0：Markdown 模式结果（无 Synthesis Agent 参与）
        state["synthesis"] = event.payload
        state["canvas_schema"] = None  # Markdown 模式无 Canvas
    elif event.event_type == "MarkdownRestored":
        # v4.0：Markdown 模式回退结果
        state["synthesis_restored"] = event.payload
        state["canvas_schema"] = None
    elif event.event_type == "CanvasUpdated":
        state["canvas_schema"] = event.payload.get("canvas_schema")
    elif event.event_type == "AgentExecution":
        # 累积执行追踪供前端展示
        state.setdefault("agent_traces", []).append(event.payload)
    elif event.event_type == "AgentExecutionCompleted":
        # 记录已完成阶段 (research/verification/synthesis/post_processor)
        state.setdefault("completed_stages", []).append(event.payload.get("stage", ""))
    if event.metadata.get("cost_usd") is not None:
        state["costs"].append({
            "agent": event.metadata.get("agent_name", "unknown"),
            "model": event.actor.model if isinstance(event.actor, BaseModel) else "deterministic",
            "usd": event.metadata.get("cost_usd", 0.0),
            "tokens": (
                event.metadata.get("tokens_input", 0)
                + event.metadata.get("tokens_output", 0)
            ),
        })
    elif event.metadata.get("tokens_input") or event.metadata.get("tokens_output"):
        state["costs"].append({
            "agent": event.metadata.get("agent_name", "unknown"),
            "model": event.actor.model if isinstance(event.actor, BaseModel) else "deterministic",
            "usd": 0.0,
            "tokens": (
                event.metadata.get("tokens_input", 0)
                + event.metadata.get("tokens_output", 0)
            ),
        })