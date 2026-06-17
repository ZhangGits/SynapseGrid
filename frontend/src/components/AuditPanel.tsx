/**
 * 审计面板组件 — 四标签页交互式审计视图
 *
 * 标签页：
 * 1. Findings — 卡片式分析要点展示
 * 2. 事件流 — 垂直时间线展示事件序列
 * 3. Agent 轨迹 — 按 Agent 分组展示执行追踪
 * 4. 版本 — 报告版本时间轴
 */
import { useState, useEffect } from "react";
import { getEvents } from "../utils/apiClient";
import { MarkdownRenderer } from "./MarkdownRenderer";
import type { TaskResponse, Finding, Conflict, VersionInfo } from "../types";

interface Props {
  response: TaskResponse;
  totalTokensAll: number;
  highlightedFindingId?: string | null;
  onFindingFocus?: (findingId: string) => void;
  versions?: VersionInfo[];
  /** 点击验证按钮时的回调 */
  onVerify?: () => void;
  /** 可回退的 finding ID 列表 */
  rollbackable?: string[];
  /** 回退回调 */
  onRollback?: (findingId: string) => void;
}

type TabKey = "findings" | "timeline" | "traces" | "versions" | "source";

export function AuditPanel({ response, totalTokensAll, highlightedFindingId, onFindingFocus, versions, onVerify, rollbackable = [], onRollback }: Props) {
  const [activeTab, setActiveTab] = useState<TabKey>("findings");
  const [realEvents, setRealEvents] = useState<any[] | null>(null);
  const { audit_metadata: meta } = response;

  // 加载真实事件流
  useEffect(() => {
    if (activeTab === "timeline") {
      getEvents(response.session_id)
        .then(data => setRealEvents(data.events))
        .catch(() => setRealEvents([]));
    }
  }, [activeTab, response.session_id]);

  return (
    <div className="audit-panel">
      <h3>审计面板</h3>

      <div className="audit-tabs">
        <button className={`audit-tab ${activeTab === "findings" ? "active" : ""}`} onClick={() => setActiveTab("findings")}>
          Findings ({meta.findings.length})
        </button>
        <button className={`audit-tab ${activeTab === "timeline" ? "active" : ""}`} onClick={() => setActiveTab("timeline")}>
          事件流
        </button>
        <button className={`audit-tab ${activeTab === "traces" ? "active" : ""}`} onClick={() => setActiveTab("traces")}>
          Agent 轨迹
        </button>
        <button className={`audit-tab ${activeTab === "versions" ? "active" : ""}`} onClick={() => setActiveTab("versions")}>
          版本 ({versions?.length ?? 0})
        </button>
        <button className={`audit-tab ${activeTab === "source" ? "active" : ""}`} onClick={() => setActiveTab("source")}>
          原文
        </button>
      </div>

      {activeTab === "findings" && (
        <FindingsTab findings={meta.findings} highlightedFindingId={highlightedFindingId} onFindingFocus={onFindingFocus} rollbackable={rollbackable} onRollback={onRollback} />
      )}
      {activeTab === "timeline" && (
        <TimelineTab 
          findings={meta.findings} 
          conflicts={meta.conflicts} 
          costBreakdown={meta.cost_breakdown} 
          eventCount={meta.event_count}
          realEvents={realEvents}
        />
      )}
      {activeTab === "traces" && (
        <TracesTab agentTraces={meta.agent_traces} totalTokens={meta.total_tokens} duration={meta.duration_seconds} />
      )}
      {activeTab === "versions" && <VersionsTab versions={versions} />}
      {activeTab === "source" && <SourceTab markdownContent={response.markdown_content} enrichedMarkdown={response.enriched_markdown} />}

      <section className="audit-session-info">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <h4 style={{ margin: 0 }}>会话信息</h4>
          {onVerify && (
            <button className="verify-btn" onClick={onVerify} title="验证报告完整性">
              🔒 验证
            </button>
          )}
        </div>
        <dl>
          <dt>会话 ID</dt>
          <dd className="mono">{meta.session_id}</dd>
          <dt>Merkle 根</dt>
          <dd className="mono">{meta.merkle_root.slice(0, 16)}...</dd>
          <dt>内容签名</dt>
          <dd className="mono">{meta.content_signature.slice(0, 16)}...</dd>
          <dt>事件数</dt>
          <dd>{meta.event_count}</dd>
          <dt>总 Token</dt>
          <dd>{totalTokensAll.toLocaleString()}</dd>
        </dl>
      </section>
    </div>
  );
}

/* ── Findings 标签页 ── */
function FindingsTab({ findings, highlightedFindingId, onFindingFocus, rollbackable = [], onRollback }: {
  findings: Finding[];
  highlightedFindingId?: string | null;
  onFindingFocus?: (findingId: string) => void;
  rollbackable?: string[];
  onRollback?: (findingId: string) => void;
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null);

  function confidenceColor(c: number): string {
    if (c >= 0.8) return "#22c55e";
    if (c >= 0.6) return "#eab308";
    return "#ef4444";
  }

  const isRollbackable = (fid: string) => rollbackable.includes(fid);

  return (
    <div className="audit-tab-content">
      {findings.length === 0 ? <p className="empty">暂无分析要点</p> : (
        <div className="finding-card-list">
          {findings.map((f) => (
            <div
              key={f.id}
              className={`finding-card ${f.rolled_back ? "rolled-back" : ""} ${f.validated ? "validated" : ""} ${highlightedFindingId === f.id ? "highlighted" : ""}`}
              onClick={() => onFindingFocus?.(f.id)}
              style={{ cursor: onFindingFocus ? "pointer" : "default" }}
            >
              <div className="finding-card-header">
                <span className="finding-card-id">{f.id}</span>
                <span className="finding-card-confidence" style={{ color: confidenceColor(f.confidence) }}>
                  {(f.confidence * 100).toFixed(0)}% 置信度
                </span>
                <div className="finding-card-actions">
                  {f.rolled_back && <span className="badge">已回退</span>}
                  {f.validated && <span className="badge-validated">已验证</span>}
                  {isRollbackable(f.id) && confirmId === f.id ? (
                    <span className="confirm-actions">
                      <button
                        className="confirm-yes"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRollback?.(f.id);
                          setConfirmId(null);
                        }}
                      >
                        确认
                      </button>
                      <button
                        className="confirm-no"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmId(null);
                        }}
                      >
                        取消
                      </button>
                    </span>
                  ) : isRollbackable(f.id) ? (
                    <button
                      className="rollback-btn-mini"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmId(f.id);
                      }}
                      title="回退该分析要点"
                    >
                      回退
                    </button>
                  ) : null}
                </div>
              </div>
              <div className="finding-card-claim">{f.claim}</div>
              {/* Phase 5: 四维度可信度摘要（如有 credibility 字段） */}
              {(f as any).credibility && (
                <div className="finding-card-credibility-scores">
                  <div className="cred-score-row">
                    <span className="cred-label">证据强度</span>
                    <div className="cred-bar-bg">
                      <div className="cred-bar-fill" style={{ width: `${((f as any).credibility.evidence_strength ?? 0.5) * 100}%`, backgroundColor: confidenceColor((f as any).credibility.evidence_strength ?? 0.5) }} />
                    </div>
                    <span className="cred-value">{(((f as any).credibility.evidence_strength ?? 0.5) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="cred-score-row">
                    <span className="cred-label">来源可靠</span>
                    <div className="cred-bar-bg">
                      <div className="cred-bar-fill" style={{ width: `${((f as any).credibility.source_reliability ?? 0.5) * 100}%`, backgroundColor: confidenceColor((f as any).credibility.source_reliability ?? 0.5) }} />
                    </div>
                    <span className="cred-value">{(((f as any).credibility.source_reliability ?? 0.5) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="cred-score-row">
                    <span className="cred-label">推理合理</span>
                    <div className="cred-bar-bg">
                      <div className="cred-bar-fill" style={{ width: `${((f as any).credibility.reasoning_soundness ?? 0.5) * 100}%`, backgroundColor: confidenceColor((f as any).credibility.reasoning_soundness ?? 0.5) }} />
                    </div>
                    <span className="cred-value">{(((f as any).credibility.reasoning_soundness ?? 0.5) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="cred-score-row">
                    <span className="cred-label">数据一致</span>
                    <div className="cred-bar-bg">
                      <div className="cred-bar-fill" style={{ width: `${((f as any).credibility.data_consistency ?? 0.5) * 100}%`, backgroundColor: confidenceColor((f as any).credibility.data_consistency ?? 0.5) }} />
                    </div>
                    <span className="cred-value">{(((f as any).credibility.data_consistency ?? 0.5) * 100).toFixed(0)}%</span>
                  </div>
                  {(f as any).credibility.assessment && (
                    <div className="cred-assessment-text">{(f as any).credibility.assessment}</div>
                  )}
                </div>
              )}
              {f.source && <div className="finding-card-source">来源: {f.source}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── 时间线标签页 ── */
function TimelineTab({ findings, conflicts, costBreakdown, eventCount, realEvents }: {
  findings: Finding[];
  conflicts: Conflict[];
  costBreakdown: { agent: string; model: string; tokens: number; usd: number }[];
  eventCount: number;
  realEvents?: any[] | null;
}) {
  // 优先使用真实事件流，回退到模拟构建
  const events = realEvents && realEvents.length > 0
    ? realEvents.map((ev: any) => ({
        type: ev.event_type.toLowerCase().replace("findingreported", "finding").replace("findingvalidated", "validation").replace("conflictdetected", "conflict").replace("synthesisgenerated", "synthesis").replace("taskstarted", "task").replace("findingrolledback", "cost"),
        label: getEventLabel(ev.event_type),
        meta: ev.event_type === "FindingReported" ? ev.payload?.finding?.id : 
              ev.event_type === "FindingValidated" ? ev.payload?.finding_id :
              ev.event_type === "ConflictDetected" ? ev.payload?.conflict?.severity :
              ev.event_type === "FindingRolledBack" ? "回退" : "",
        body: ev.semantic_digest || ev.event_type,
      }))
    : buildTimelineEvents(findings, conflicts, costBreakdown);
  return (
    <div className="audit-tab-content">
      {events.length === 0 ? <p className="empty">暂无事件数据</p> : (
        <div className="timeline">
          {events.map((ev, idx) => (
            <div key={idx} className={`timeline-item ${ev.type}`}>
              <div className="timeline-dot" />
              <div className="timeline-content">
                <div className="timeline-header"><span className="timeline-type">{ev.label}</span><span className="timeline-meta">{ev.meta}</span></div>
                <div className="timeline-body">{ev.body}</div>
              </div>
            </div>
          ))}
          <div className="timeline-end">共 {eventCount} 个事件</div>
        </div>
      )}
    </div>
  );
}

function getEventLabel(eventType: string): string {
  const labels: Record<string, string> = {
    "TaskStarted": "🚀 任务启动",
    "FindingReported": "🔍 发现要点",
    "FindingValidated": "✅ 验证通过",
    "ConflictDetected": "⚠️ 检测到矛盾",
    "SynthesisGenerated": "📝 综合报告生成",
    "SynthesisRestored": "🔄 报告恢复",
    "FindingRolledBack": "↩️ 回退",
  };
  return labels[eventType] || eventType;
}

function buildTimelineEvents(findings: Finding[], conflicts: Conflict[], costBreakdown: { agent: string; model: string; tokens: number; usd: number }[]) {
  const events: { type: string; label: string; meta: string; body: string }[] = [];
  events.push({ type: "task", label: "🚀 任务启动", meta: "", body: "用户提交分析任务" });
  findings.forEach((f) => events.push({ type: "finding", label: "🔍 发现要点", meta: f.id, body: f.claim }));
  findings.filter((f) => f.validated).forEach((f) => events.push({ type: "validation", label: "✅ 验证通过", meta: f.id, body: `置信度 ${(f.confidence * 100).toFixed(0)}%` }));
  conflicts.forEach((c) => events.push({ type: "conflict", label: "⚠️ 检测到矛盾", meta: `${c.severity} 严重度`, body: `${c.finding_a} vs ${c.finding_b}: ${c.type}` }));
  events.push({ type: "synthesis", label: "📝 综合报告生成", meta: "", body: `基于 ${findings.filter((f) => f.validated && !f.rolled_back).length} 条有效要点` });
  costBreakdown.forEach((c) => events.push({ type: "cost", label: "💰 成本记录", meta: c.agent, body: `${c.model} | ${c.tokens.toLocaleString()} tokens | $${c.usd.toFixed(6)}` }));
  return events;
}

/* ── Agent 轨迹标签页 ── */
function TracesTab({ agentTraces, totalTokens, duration }: {
  agentTraces?: { agent_id: string; model: string; duration_ms: number; tokens_input: number; tokens_output: number; prompt_summary: string; output_summary: string; error: string | null }[];
  totalTokens: number;
  duration: number;
}) {
  return (
    <div className="audit-tab-content">
      <div className="trace-stats">
        <div className="trace-stat"><span className="trace-stat-value">{totalTokens.toLocaleString()}</span><span className="trace-stat-label">总 Token</span></div>
        <div className="trace-stat"><span className="trace-stat-value">{duration.toFixed(1)}s</span><span className="trace-stat-label">执行耗时</span></div>
        <div className="trace-stat"><span className="trace-stat-value">{agentTraces?.length ?? 0}</span><span className="trace-stat-label">Agent 调用</span></div>
      </div>
      {(!agentTraces || agentTraces.length === 0) ? <p className="empty">暂无 Agent 执行追踪数据</p> : (
        <div className="trace-list-detailed">
          {agentTraces.map((t, i) => (
            <div key={i} className={`trace-card ${t.error ? "error" : ""}`}>
              <div className="trace-card-header"><span className="trace-agent">{t.agent_id}</span><span className="trace-model">{t.model}</span><span className="trace-duration">{t.duration_ms}ms</span></div>
              <div className="trace-card-body">
                <div className="trace-tokens"><span>输入: {t.tokens_input.toLocaleString()}</span><span>输出: {t.tokens_output.toLocaleString()}</span></div>
              </div>
              {t.error && <div className="trace-error">错误: {t.error}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── 原文标签页 ── */
function SourceTab({ markdownContent, enrichedMarkdown }: { markdownContent: string; enrichedMarkdown?: string }) {
  const [showEnriched, setShowEnriched] = useState(true);
  const displayContent = showEnriched && enrichedMarkdown ? enrichedMarkdown : markdownContent;

  // 去除审计头（YAML frontmatter）
  const cleanContent = displayContent.replace(/^---\n[\s\S]*?\n---\n\n/, "");

  return (
    <div className="audit-tab-content">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
          {showEnriched ? "增强 Markdown（含 provenance 标记）" : "原始 Markdown"}
        </span>
        <button
          onClick={() => setShowEnriched(!showEnriched)}
          style={{
            background: "var(--bg-tertiary)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            padding: "4px 12px",
            color: "var(--text)",
            fontSize: "0.8rem",
            cursor: "pointer",
          }}
        >
          {showEnriched ? "查看原文" : "查看增强版"}
        </button>
      </div>
      <div
        style={{
          background: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: 16,
          maxHeight: "60vh",
          overflowY: "auto",
          color: "var(--text)",
        }}
      >
        <MarkdownRenderer content={cleanContent} />
      </div>
    </div>
  );
}

/* ── 版本时间轴标签页 ── */
function VersionsTab({ versions }: { versions?: VersionInfo[] }) {
  if (!versions || versions.length === 0) return <p className="empty">暂无版本数据</p>;
  return (
    <div className="audit-tab-content">
      <div className="version-list">
        {versions.map((v, idx) => (
          <div key={v.version} className={`version-item ${v.event_type === "SynthesisRestored" ? "restored" : "generated"}`}>
            <div className="version-header">
              <span className="version-badge">{idx + 1}</span>
              <span className="version-type">{v.event_type === "SynthesisGenerated" ? "📝 生成" : "🔄 恢复"}</span>
              <span className="version-finding-count">{v.finding_count} 个 finding</span>
            </div>
            <div className="version-summary">{v.summary}</div>
            {v.created_at && <div className="version-time">{v.created_at}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}