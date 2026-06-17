/**
 * SynapseGrid MVP 前端类型定义
 *
 * 定义与后端 API 交互的所有数据类型，包括：
 * - Finding / Conflict / CostRecord: 审计元数据子类型
 * - TaskResponse: 后端返回的完整响应
 * - CanvasSchema / CanvasComponent: 画布模式类型
 * - IntentPayload / ActionLogItem: 用户意图类型
 * - ChatMessage / LlmConfig / PerAgentLlm: 前端状态类型
 */

/** 分析要点 */
export interface Finding {
  id: string;
  claim: string;
  source: string;
  confidence: number;
  agent: string;
  model: string;
  cost_usd: number;
  /** 论据/证据（可选，部分 finding 可能无此字段） */
  evidence?: string;
  rolled_back?: boolean;
  validated?: boolean;
}

/** 矛盾 */
export interface Conflict {
  id: string;
  finding_a: string;
  finding_b: string;
  type: string;
  severity: "low" | "medium" | "high";
}

/** 成本记录 */
export interface CostRecord {
  agent: string;
  model: string;
  usd: number;
  tokens: number;
}

/** 报告版本信息 */
export interface VersionInfo {
  version: number;
  event_type: string;
  created_at: string;
  summary: string;
  finding_count: number;
}

/** 后端任务响应 */
export interface TaskResponse {
  session_id: string;
  markdown_content: string;
  enriched_markdown?: string;
  canvas_schema?: LogicGraph | null;
  audit_metadata: {
    session_id: string;
    merkle_root: string;
    content_signature: string;
    findings: Finding[];
    conflicts: Conflict[];
    cost_breakdown: CostRecord[];
    total_tokens: number;
    event_count: number;
    duration_seconds: number;
    budget_remaining?: number;
    agent_traces?: {
      agent_id: string;
      model: string;
      duration_ms: number;
      tokens_input: number;
      tokens_output: number;
      prompt_summary: string;
      output_summary: string;
      error: string | null;
    }[];
  };
  lineage_data: {
    nodes: { id: string; type: string; label: string }[];
    edges: { source: string; target: string; relation: string }[];
  };
  rollback_options: {
    rollbackable_findings: string[];
    branches: string[];
  };
}

/** 信誉度评估（四维度） */
export interface CredibilityAssessment {
  finding_id: string;
  evidence_strength: number;
  source_reliability: number;
  reasoning_soundness: number;
  data_consistency: number;
  overall_credibility: number;
  assessment: string;
  concerns: string[];
  suggestions: string[];
}

// ── 论证结构图类型（Phase 4 v4.0） ──────────────────

 export interface LogicNode {
   id: string;
   type: "question" | "conclusion" | "claim" | "evidence";
   label: string;
   /** Synthesis Agent 提取的摘要（1-2 句简洁描述），优先于 label 用于画布显示 */
   summary?: string;
   finding_id?: string;
   credibility: number;
   rolled_back: boolean;
   importance: number;
 }

export interface LogicEdge {
  from_id: string;
  to_id: string;
  type: "supports" | "perspective_difference" | "tension" | "genuine_contradiction";
  description?: string;
}

export interface LogicGraph {
  nodes: LogicNode[];
  edges: LogicEdge[];
}

// ── 画布类型 ─────────────────────────────────────────────────

/** 组件位置 */
export interface Position {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Markdown 组件 */
export interface MarkdownComponent {
  id: string;
  type: "markdown";
  semantic_tags: string[];
  priority_level: number;
  version: number;
  position?: Position;
  content: string;
}

/** KPI 卡片组件 */
export interface KpiCardComponent {
  id: string;
  type: "kpi_card";
  semantic_tags: string[];
  priority_level: number;
  version: number;
  position?: Position;
  visual_config: {
    prefix: string;
    suffix: string;
    precision: number;
    color: string;
  };
  value: number;
  label: string;
}

/** 柱状图组件 */
export interface BarChartComponent {
  id: string;
  type: "bar_chart";
  semantic_tags: string[];
  priority_level: number;
  version: number;
  position?: Position;
  visual_config: {
    color: string;
    show_legend: boolean;
    orientation: "vertical" | "horizontal";
    stacked: boolean;
  };
  categories: string[];
  values: number[];
}

/** 分析要点文本框组件 — 画布模式下每个 finding 渲染为一个独立文本框 */
export interface FindingBoxComponent {
  id: string;
  type: "finding_box";
  semantic_tags: string[];
  priority_level: number;
  version: number;
  position?: Position;
  /** 要点 ID */
  finding_id: string;
  /** 观点/主张 */
  claim: string;
  /** 论据/证据 */
  evidence: string;
  /** 置信度 (0-1) */
  confidence: number;
  /** 来源 */
  source: string;
}

/** 画布组件联合类型 */
export type CanvasComponent = MarkdownComponent | KpiCardComponent | BarChartComponent | FindingBoxComponent;

/** 画布模式 */
export interface CanvasSchema {
  version: number;
  layout_type: "grid" | "report";
  components: CanvasComponent[];
}

/** 用户操作日志项 */
export interface ActionLogItem {
  action: "drag" | "click" | "input";
  target_id: string;
  new_position?: Position;
  detail?: string;
}

/** 用户意图负载 */
export interface IntentPayload {
  type: "LAYOUT_ADJUST" | "DATA_FOCUS" | "STYLE_CHANGE" | "EXPLORATORY" | "COMPOUND_ACTION";
  base_version: number;
  targets: string[];
  action_log: ActionLogItem[];
  user_text: string;
}

/** 聊天消息 */
export interface ChatMessage {
  id: string;
  prompt: string;
  response?: TaskResponse;
  /** 异步任务的 session_id（用于实时进度跟踪） */
  session_id?: string;
  /** 已完成的阶段列表（research/verification/synthesis/post_processor） */
  completed_stages?: string[];
}

/** LLM 配置 */
export interface LlmConfig {
  provider: "chatgpt" | "claude" | "deepseek" | "qwen" | "kimi" | "gemini" | "custom";
  model: string;
  api_key: string;
  base_url?: string;
}

/** 每个 Agent 的 LLM 配置 */
export interface PerAgentLlm {
  research: LlmConfig;
  verification: LlmConfig;
  synthesis: LlmConfig;
}
