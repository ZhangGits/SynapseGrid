# SynapseGrid Agent 交互方式分析

**日期**: 2026-06-14

---

## 一、交互架构总览

```
用户输入 (prompt)
       │
       ▼
 ┌─────────────────────┐
 │    Orchestrator     │  总调度器：串行编排 3 个 Agent 的执行顺序
 │    (run_task)       │  管理会话、预算、事件持久化
 └─────────────────────┘
       │
       ├── Phase 1 ──────────────────────────────────────────
       │
       ▼
 ┌──────────────┐    ┌──────────────────────┐
 │ Research     │───▶│ FindingReported 事件  │  × N
 │ Agent        │    │ (f1, f2, f3...)      │
 │ (r_llm)      │    └──────────┬───────────┘
 └──────────────┘               │
                     ┌──────────▼───────────┐
                     │  单写者队列 → SQLite  │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │  状态投影器           │
                     │  state["findings"]   │
                     │  = {f1: {...}, ...}  │
                     └──────────────────────┘
       │
       ├── Aggregation ─────────────────────────────────────
       │         │
       │         ▼  从 state["findings"] 提取 findings 列表
       │   AggregationCompleted 事件
       │
       ├── Phase 2 ──────────────────────────────────────────
       │
       ▼
 ┌──────────────┐    ┌──────────────────────┐
 │ Verification │───▶│ FindingValidated 事件 │  × N
 │ Agent        │    │ ConflictDetected 事件 │  × M
 │ (v_llm)      │    └──────────┬───────────┘
 └──────────────┘               │
                     ┌──────────▼───────────┐
                     │  单写者队列 → SQLite  │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │  状态投影器           │
                     │  state["conflicts"]  │
                     │  findings[...]       │
                     │    ["validated"]=True│
                     └──────────────────────┘
       │
       ├── Phase 3 ──────────────────────────────────────────
       │
       ▼
 ┌──────────────┐    ┌──────────────────────────┐
 │ Synthesis    │───▶│ SynthesisGenerated 事件    │
 │ Agent        │    │ (固化 LLM 输出，不可变)     │
 │ (s_llm)      │    └──────────┬───────────────┘
 └──────────────┘               │
                     ┌──────────▼───────────┐
                     │  单写者队列 → SQLite  │
                     └──────────────────────┘
       │
       ▼
 ┌───────────────────────────────────────────┐
 │  _build_response()                        │
 │  从 SQLite 读取事件 → 计算 Merkle 根      │
 │  从内存投影读取 findings/conflicts/costs  │
 │  附加 content_signature                   │
 │  构建 JSON 复合响应                        │
 └───────────────────────────────────────────┘
```

---

## 二、交互方式是**事件溯源黑板模式**

Agent 之间**不直接通信**。每个 Agent 只做三件事：

1. 从**共享内存投影**（`state` 字典）读取上游产出
2. 调用 LLM 完成自己的任务
3. 生成**事件**追加到单写者队列 → SQLite → 投影更新内存状态

```
Agent A 产出            Agent B 消费
    │                       ▲
    ▼                       │
  Event ──▶ SQLite ──▶ 投影器 ──▶ state dict
                                   │
                                   ▼
                              Agent B.run(state)
```

这是典型的 **Event Sourcing + CQRS** 模式：事件是唯一真相来源（source of truth），内存状态是事件的投影结果，Agent 之间通过共享状态（Blackboard）间接协作。

---

## 三、每个 Agent 具体消费和生产的数据

### Research Agent

| 维度 | 内容 |
|------|------|
| **消费** | 用户 prompt、LLMConfig (provider/model/api_key) |
| **生产** | `FindingReported` 事件 × N |
| **事件 payload** | `{source_id, finding: {id, claim, source, confidence, agent, model, cost_usd}}` |
| **投影结果** | `state["findings"]["f1"] = {id, claim, source, confidence, ...}` |
| **LLM 调用方式** | prompt ≤ 200 字符 → 单次调用；prompt > 200 字符 → 拆为 2 路 `asyncio.gather` 并行调用 |
| **失败回退** | 生成 2 条确定性占位 finding |

### Verification Agent

| 维度 | 内容 |
|------|------|
| **消费** | `state["findings"]` 字典（所有 findings） |
| **生产** | `FindingValidated` 事件 × N + `ConflictDetected` 事件 × M |
| **事件 payload** | `{finding_id, confidence}` / `{conflict: {id, finding_a, finding_b, type, severity}}` |
| **投影结果** | `findings[fid]["validated"] = True`、`state["conflicts"]["c1"] = {...}` |
| **LLM 调用方式** | Phase 1: `asyncio.gather` 并行验证每条 finding；Phase 2: 单次批量冲突检测 |
| **预算闸门** | 如果累计成本接近预算上限 → 跳过 LLM，直接 fallback |

### Synthesis Agent

| 维度 | 内容 |
|------|------|
| **消费** | `state["task"]["prompt"]` + `state["findings"]`（仅 active）+ `state["conflicts"]` + 场景模板 |
| **生产** | `SynthesisGenerated` 事件 × 1（`is_llm_output=True`） |
| **事件 payload** | `{markdown_content, audit_metadata: {findings[], conflicts[], provider, model}}` |
| **投影结果** | `state["synthesis"] = {...}` |
| **LLM 输出处理** | 作为不可变事件固化——回退时从 SQLite 恢复，**永不重新调用 LLM** |

---

## 四、上下文传递机制

每个 Agent 调用 LLM 时，不是传递完整的原始数据，而是将上游产出压缩为 ID+摘要的黑板协议（Blackboard Protocol）：

### Research → Verification

```python
# 传递的是 findings 的压缩视图（~70% token 节约）
[
  {"id": "f1", "src": "llm_extraction", "conf": 0.85, "summary": "C的名次在A之前"},
  {"id": "f2", "src": "user_prompt", "conf": 0.95, "summary": "B的名次在D之前"}
]
```

### Verification + Aggregation → Synthesis

```python
# 传递 findings 摘要 + conflicts 摘要
Finding items: [{"id": "f1", "conf": 0.85, "src": "llm_extraction", "s": "C的名次在A之前"}, ...]
Conflict items: [{"id": "c1", "a": "f1", "b": "f3", "t": "contradiction", "sev": "medium"}, ...]
```

完整 claim 文本存在 `state["findings"]` 中，供前端审计面板展示，但不送入下游 Agent 的 LLM 调用——节约 token 成本。

---

## 五、事件流与时间线

一次完整任务调用的事件序列（以 3 条 finding、无冲突为例）：

```
版本  事件类型              生产者
────  ──────────────────     ──────────
v1    TaskStarted            Orchestrator
v2    FindingReported        Research Agent (f1)
v3    FindingReported        Research Agent (f2)
v4    FindingReported        Research Agent (f3)
v5    AgentExecution         Orchestrator (research 追踪)
v6    AggregationCompleted   聚合器 (确定性)
v7    FindingValidated       Verification Agent (f1)
v8    FindingValidated       Verification Agent (f2)
v9    FindingValidated       Verification Agent (f3)
v10   AgentExecution         Orchestrator (verification 追踪)
v11   SynthesisGenerated     Synthesis Agent (固化 LLM 输出)
v12   AgentExecution         Orchestrator (synthesis 追踪)
```

每个事件经过：**入队 → 单写者写入 SQLite → 哈希签名 → 投影到内存状态**。

回退时追加 `FindingRolledBack` + `SynthesisRestored` 补偿事件，不修改历史。

---

## 六、关键设计决策

| 决策 | 说明 |
|------|------|
| **Agent 不直接互相调用** | 通过共享状态投影间接协作，解耦 Agent 实现 |
| **事件是唯一真相来源** | Agent 的输出写入 Append-Only SQLite，崩溃后可重放重建 |
| **LLM 输出作为不可变事件固化** | Synthesis 的输出写入 `SynthesisGenerated` 事件，回退时不重新调用 LLM |
| **单写者队列** | 所有事件写入经过 `asyncio.Queue`，杜绝 SQLite 锁竞争 |
| **每个 Agent 可独立选择 LLM** | `llm_research` / `llm_verification` / `llm_synthesis` 可不同 provider/model |
| **预算全局跟踪** | `BudgetTracker` 跨 Agent 累计成本，接近上限时跳过 Verification |
