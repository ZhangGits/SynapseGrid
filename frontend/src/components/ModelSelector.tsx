/**
 * 模型选择器组件 — 为每个 Agent 配置 LLM 模型
 *
 * 支持：
 * - 为 Research、Verification、Synthesis 分别配置模型
 * - 锁定 Verification 和 Synthesis 使用与 Research 相同的模型
 * - 持久化配置到 localStorage
 * - 可折叠/展开模式，默认收起以节省顶部空间
 */

import { useState, useEffect, useRef } from "react";
import type { LlmConfig, PerAgentLlm } from "../types";

interface Props {
  initialRows: PerAgentLlm;
  initialLocked?: { verification: boolean; synthesis: boolean };
  onChange: (config: PerAgentLlm) => void;
}

const PROVIDERS = [
  { value: "chatgpt", label: "ChatGPT" },
  { value: "claude", label: "Claude" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "qwen", label: "Qwen" },
  { value: "kimi", label: "Kimi" },
  { value: "gemini", label: "Gemini" },
  { value: "custom", label: "自定义" },
];

const DEFAULT_MODELS: Record<string, string> = {
  chatgpt: "gpt-4o-mini",
  claude: "claude-3-5-sonnet-latest",
  deepseek: "deepseek-chat",
  qwen: "qwen-plus",
  kimi: "moonshot-v1-8k",
  gemini: "gemini-1.5-flash",
  custom: "",
};

/** Agent 名称联合类型 */
type AgentName = keyof PerAgentLlm;

/** 可锁定的 Agent 名称 */
type LockableAgent = "verification" | "synthesis";

/** 锁定状态类型 */
type LockState = Record<LockableAgent, boolean>;

export function PerAgentModelSelector({ initialRows, initialLocked, onChange }: Props) {
  const [rows, setRows] = useState<PerAgentLlm>(initialRows);
  const [locked, setLocked] = useState<LockState>({
    verification: initialLocked?.verification ?? true,
    synthesis: initialLocked?.synthesis ?? true,
  });
  /** 折叠/展开状态，默认收起 */
  const [expanded, setExpanded] = useState(false);
  /** 容器引用，用于检测点击外部区域 */
  const containerRef = useRef<HTMLDivElement>(null);

  /** 点击外部区域时自动收起配置面板 */
  useEffect(() => {
    if (!expanded) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    };
    // 使用 mousedown 而非 click，响应更快
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [expanded]);

  /** 更新指定 Agent 的配置 */
  const updateAgent = (agent: AgentName, field: keyof LlmConfig, value: string) => {
    const updated = { ...rows };
    updated[agent] = { ...updated[agent], [field]: value };

    // 如果 provider 改变，自动设置默认模型
    if (field === "provider") {
      updated[agent].model = DEFAULT_MODELS[value] || "";
    }

    // 如果锁定，同步更新 verification 和 synthesis
    if (agent === "research") {
      if (locked.verification) {
        updated.verification = { ...updated[agent] };
      }
      if (locked.synthesis) {
        updated.synthesis = { ...updated[agent] };
      }
    }

    setRows(updated);
    onChange(updated);
  };

  /** 切换锁定状态 */
  const toggleLock = (target: LockableAgent) => {
    const newLocked = { ...locked, [target]: !locked[target] };
    setLocked(newLocked);

    // 锁定时，将当前 research 配置复制到目标 Agent
    if (newLocked[target]) {
      const updated = { ...rows };
      updated[target] = { ...rows.research };
      setRows(updated);
      onChange(updated);
    }
  };

  /** 渲染单个 Agent 的配置行 */
  const renderRow = (agent: AgentName, label: string, showLock?: boolean) => (
    <div className="model-row" key={agent}>
      <span className="model-label">{label}</span>
      <select
        value={rows[agent].provider}
        onChange={(e) => updateAgent(agent, "provider", e.target.value)}
      >
        {PROVIDERS.map((p) => (
          <option key={p.value} value={p.value}>{p.label}</option>
        ))}
      </select>
      <input
        type="text"
        value={rows[agent].model}
        onChange={(e) => updateAgent(agent, "model", e.target.value)}
        placeholder="模型名称"
        className="model-input"
      />
      <input
        type="password"
        value={rows[agent].api_key}
        onChange={(e) => updateAgent(agent, "api_key", e.target.value)}
        placeholder="API Key"
        className="api-key-input"
      />
      {showLock && (
        <button
          className={`lock-btn ${locked[agent as LockableAgent] ? "locked" : ""}`}
          onClick={() => toggleLock(agent as LockableAgent)}
          title={locked[agent as LockableAgent] ? "与 Research 同步" : "独立配置"}
        >
          {locked[agent as LockableAgent] ? "🔗" : "🔓"}
        </button>
      )}
    </div>
  );

  return (
    <div className="model-selector" ref={containerRef}>
      {/* 折叠/展开切换按钮 */}
      <button
        className="model-toggle-btn"
        onClick={() => setExpanded(!expanded)}
        title={expanded ? "收起 API 配置" : "展开 API 配置"}
      >
        <span className="model-toggle-icon">{expanded ? "▼" : "▶"}</span>
        <span>API 配置</span>
        <span className="model-toggle-badge">
          {rows.research.provider} / {rows.research.model}
        </span>
      </button>
      {/* 可折叠的配置面板 */}
      {expanded && (
        <div className="model-config-body">
          {renderRow("research", "研究")}
          {renderRow("verification", "验证", true)}
          {renderRow("synthesis", "综合", true)}
        </div>
      )}
    </div>
  );
}
