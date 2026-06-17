/**
 * SynapseGrid MVP 前端入口 — 主应用组件
 *
 * 负责：
 * 1. 管理聊天消息状态（含 localStorage 持久化）
 * 2. 管理 LLM 配置和 Agent 配置
 * 3. 管理模板选择和输出模式
 * 4. 处理任务提交、回退、画布反馈
 * 5. 渲染聊天面板、侧边栏（审计/画布）
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { AuditPanel } from "./components/AuditPanel";
import { CanvasViewer } from "./components/CanvasViewer";
import { ChatHistory } from "./components/ChatHistory";
import { ChatInput } from "./components/ChatInput";
import { MarkdownOverlay } from "./components/MarkdownOverlay";
import { MarkdownRenderer } from "./components/MarkdownRenderer";
import { PerAgentModelSelector } from "./components/ModelSelector";
import type { ChatMessage, LlmConfig, PerAgentLlm, TaskResponse } from "./types";
import { createTask, getTaskProgress, getTaskResult, rollbackFinding, getVersions, verifySessionSimple } from "./utils/apiClient";
import { VerificationModal } from "./components/VerificationModal";
import type { VersionInfo } from "./types";
import "./styles.css";

/** 从 Vite 环境变量获取 API 基础路径 */
const API_BASE = (import.meta as any).env?.VITE_API_BASE ?? "http://localhost:8000/api/v1";

let _id = 0;
/** 生成唯一消息 ID */
function uid() { return "msg_" + (++_id); }

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadMessages());
  const [activeMsg, setActiveMsg] = useState<ChatMessage | null>(null);
  const [auditMsg, setAuditMsg] = useState<ChatMessage | null>(null);
  const [llm, setLlm] = useState<LlmConfig>(() => loadLlmConfig());
  const [agentLlm, setAgentLlm] = useState<PerAgentLlm>(() => loadAgentLlm());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 持久化 LLM 配置到 localStorage
  useEffect(() => { saveLlmConfig(llm); }, [llm]);
  useEffect(() => { saveAgentLlm(agentLlm); }, [agentLlm]);
  useEffect(() => { saveMessages(messages); }, [messages]);
  const [template, setTemplate] = useState<string>(() => {
    try { return localStorage.getItem("sg_template") ?? "general"; }
    catch { return "general"; }
  });
  useEffect(() => { try { localStorage.setItem("sg_template", template); } catch {} }, [template]);

  // 从 /health 端点动态加载模板选项
  const [templateOptions, setTemplateOptions] = useState<string[]>(() => ["general", "finance", "legal"]);
  useEffect(() => {
    fetch(`${API_BASE.replace(/\/api\/v1\/?$/, "")}/health`)
      .then((r) => r.json())
      .then((data) => {
        if (data.templates?.length) setTemplateOptions(data.templates);
      })
      .catch(() => {});
  }, []);

  const [outputMode, setOutputMode] = useState<string>(() => {
    try { return localStorage.getItem("sg_output_mode") ?? "markdown"; }
    catch { return "markdown"; }
  });
  useEffect(() => { try { localStorage.setItem("sg_output_mode", outputMode); } catch {} }, [outputMode]);

  // 侧边栏标签页状态
  const [sidebarTab, setSidebarTab] = useState<"audit" | "canvas">("audit");
  /** 当前高亮的 Finding ID（用于双向联动） */
  const [highlightedFindingId, setHighlightedFindingId] = useState<string | null>(null);
  /** 版本列表 */
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  /** 验证弹窗状态 */
  const [verifyResult, setVerifyResult] = useState<any | null>(null);
  /** Canvas 全屏模式 */
  const [canvasFullscreen, setCanvasFullscreen] = useState(false);

  // 收到画布响应时自动切换到画布标签
  useEffect(() => {
    if (activeMsg?.response?.canvas_schema) {
      setSidebarTab("canvas");
    }
  }, [activeMsg?.response?.canvas_schema]);

  // 已查看过的消息 ID 集合（用于控制打字机效果只出现一次）
  const viewedIds = useRef(new Set<string>());
  // 当前正在播放动画的消息 ID（用于首次查看时启用动画）
  const [animatingId, setAnimatingId] = useState<string | null>(null);

  // 可拖动分隔条状态
  const [splitPos, setSplitPos] = useState<number>(() => {
    try { return parseInt(localStorage.getItem("sg_split_pos") ?? "420", 10); }
    catch { return 420; }
  });
  const splitRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);

  // 可拖动分隔条逻辑
  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest(".split-handle")) {
        isDragging.current = true;
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
      }
    };
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const workspace = document.querySelector(".workspace");
      if (!workspace) return;
      const rect = workspace.getBoundingClientRect();
      const newPos = Math.max(300, Math.min(800, rect.right - e.clientX));
      setSplitPos(newPos);
    };
    const handleMouseUp = () => {
      if (isDragging.current) {
        isDragging.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        try { localStorage.setItem("sg_split_pos", String(splitPos)); } catch {}
      }
    };
    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [splitPos]);

  const last = messages.length > 0 ? messages[messages.length - 1] : null;

  // 计算所有消息的总 Token 数
  const totalTokensAll = messages.reduce((sum: number, m: ChatMessage) => {
    if (!m.response) return sum;
    return sum + (m.response.audit_metadata.total_tokens ??
      m.response.audit_metadata.cost_breakdown.reduce((s: number, r: { tokens: number }) => s + r.tokens, 0));
  }, 0);

  // 选择审计目标：显式指定的 auditMsg，或最新的已完成响应
  const auditTarget = auditMsg ?? (last?.response ? last : null);

  /** 执行分析任务：异步模式，立即返回 session_id，轮询进度 */
  async function runTask(prompt: string) {
    setLoading(true);
    setError(null);

    // 立即显示用户气泡和待处理的机器人气泡
    const pendingId = uid();
    const pendingMsg: ChatMessage = { id: pendingId, prompt };
    setMessages((prev: ChatMessage[]) => [...prev, pendingMsg]);

    // 从已完成的消息构建结构化历史
    const completedMsgs = messages.filter((m: ChatMessage) => m.response);
    const recent = completedMsgs.slice(-3);
    const history = recent.length > 0
      ? recent.map((m: ChatMessage, i: number) => {
          const ans = m.response!.markdown_content || "";
          const ansBrief = ans.replace(/^---[\s\S]*?---\n/, "").slice(0, 500);
          return `Q${i + 1}: ${m.prompt}\nA${i + 1}: ${ansBrief}`;
        }).join("\n\n")
      : undefined;

    try {
      // 1. 创建异步任务，立即获得 session_id
      const { session_id } = await createTask(prompt, llm, agentLlm, template, outputMode, history);
      // 更新 pending 消息记录 session_id
      setMessages((prev: ChatMessage[]) => prev.map((m: ChatMessage) =>
        m.id === pendingId ? { ...m, session_id } : m,
      ));

      // 2. 轮询进度
      const result = await pollTaskProgress(session_id, pendingId);
      if (result) {
        setMessages((prev: ChatMessage[]) => prev.map((m: ChatMessage) =>
          m.id === pendingId ? { ...m, response: result } : m,
        ));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Task failed");
    } finally {
      setLoading(false);
    }
  }

  /** 轮询任务进度，直到完成 */
  async function pollTaskProgress(sessionId: string, pendingId: string): Promise<TaskResponse | null> {
    const POLL_INTERVAL = 1000; // 每秒轮询一次
    const MAX_POLL_TIME = 300000; // 最多轮询5分钟
    const startTime = Date.now();

    while (Date.now() - startTime < MAX_POLL_TIME) {
      try {
        const progress = await getTaskProgress(sessionId);
        // 更新 pending 消息的 completed_stages（用于 AgentAnalysisNodes 实时显示）
        setMessages((prev: ChatMessage[]) => prev.map((m: ChatMessage) =>
          m.id === pendingId ? { ...m, completed_stages: progress.completed_stages } : m,
        ));

        if (progress.has_result) {
          const result = await getTaskResult(sessionId);
          return result;
        }
      } catch (e) {
        // 轮询出错继续尝试
      }
      await sleep(POLL_INTERVAL);
    }
    return null;
  }

  /** 查看报告：设置 activeMsg 以在侧边栏显示 */
  function viewReport(msg: ChatMessage) {
    // Canvas 模式直接全屏显示论证结构
    if (msg.response?.canvas_schema) {
      setActiveMsg(msg);
      setCanvasFullscreen(true);
      setAnimatingId(null);
      return;
    }

    // 检测是否有已回退的 finding
    const hasRolledBack = msg.response?.audit_metadata.findings.some(f => f.rolled_back);
    if (hasRolledBack) {
      // 弹窗询问用户是否要基于未回退的信息重新综合
      const confirmed = window.confirm(
        "检测到有已回退的分析要点。是否要基于未回退的信息重新生成综合报告？\n\n" +
        "注意：这将消耗额外的 Token。"
      );
      if (confirmed) {
        // 用户确认重新综合 → 调用后端重新执行 Synthesis
        setLoading(true);
        setError(null);
        const sessionId = msg.response!.session_id;
        fetch(`${API_BASE}/tasks/${sessionId}/resynthesize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
          .then(r => {
            if (!r.ok) throw new Error("重新综合失败");
            return r.json();
          })
          .then((updated: TaskResponse) => {
            // 更新消息中的 response
            setMessages((prev: ChatMessage[]) => prev.map((m: ChatMessage) =>
              m.id === msg.id ? { ...m, response: updated } : m
            ));
            setActiveMsg({ ...msg, response: updated });
            setAnimatingId(null);
          })
          .catch(err => setError(err instanceof Error ? err.message : "Resynthesis failed"))
          .finally(() => setLoading(false));
        return;
      }
      // 用户取消 → 直接显示当前报告（继续往下执行）
    }
    setActiveMsg(msg);
    // Canvas 模式不需要打字机效果
    if (msg.response?.canvas_schema) {
      setAnimatingId(null);
    } else if (animatingId !== msg.id) {
      // 首次查看此消息时启用打字机动画
      setAnimatingId(msg.id);
    }
  }

  /** 查看审计：设置 auditMsg 以在侧边栏显示审计面板 */
  async function viewAudit(msg: ChatMessage) {
    setActiveMsg(null);
    setAuditMsg(msg);
    // 加载版本列表
    if (msg.response) {
      try {
        const data = await getVersions(msg.response.session_id);
        setVersions(data.versions);
      } catch {
        setVersions([]);
      }
    }
  }

  /** 回退分析要点 */
  const rollback = useCallback(async (findingId: string) => {
    if (!last || !last.response) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await rollbackFinding(last.response.session_id, findingId);
      setMessages((prev: ChatMessage[]) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], response: updated };
        return next;
      });
      setActiveMsg((prev: ChatMessage | null) => prev && prev.id === last.id
        ? { ...prev, response: updated }
        : prev
      );
      setAuditMsg((prev: ChatMessage | null) => prev && prev.id === last.id
        ? { ...prev, response: updated }
        : prev
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rollback failed");
    } finally {
      setLoading(false);
    }
  }, [last]);

  return (
    <main>
      <header>
        <div>
          <h1>SynapseGrid</h1>
          <p>可审计的事件溯源 MVP</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <PerAgentModelSelector
            initialRows={agentLlm}
            initialLocked={{ verification: lockedFromStorage("verification"), synthesis: lockedFromStorage("synthesis") }}
            onChange={(pa: PerAgentLlm) => {
              setAgentLlm(pa);
              setLlm(pa.research);
            }}
          />
          <select
            className="template-select"
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            title="分析场景"
          >
            {templateOptions.map((t: string) => (
              <option key={t} value={t}>{t === "general" ? "通用" : t === "finance" ? "金融" : t === "legal" ? "法律" : t}</option>
            ))}
          </select>
          {messages.length > 0 && (
            <button
              className="clear-chat-btn"
              onClick={() => {
                setMessages([]);
                setActiveMsg(null);
                setAuditMsg(null);
                try { localStorage.removeItem("sg_messages"); } catch {}
              }}
              title="清空对话"
            >
              清空对话
            </button>
          )}
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="workspace">
        <div className="chat-pane">
          <ChatHistory
            messages={messages}
            onViewReport={viewReport}
            onViewAudit={viewAudit}
            loading={loading}
            outputMode={outputMode}
            onUseExample={(text: string) => {
              (window as any).__sg_example_prompt = text;
              setTimeout(() => {
                const ta = document.querySelector<HTMLTextAreaElement>(".chat-input textarea");
                if (ta) {
                  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, "value"
                  )!.set!;
                  nativeInputValueSetter.call(ta, text);
                  ta.dispatchEvent(new Event("input", { bubbles: true }));
                  ta.focus();
                }
              }, 0);
            }}
          />
          <ChatInput
            loading={loading}
            onSubmit={runTask}
            controls={
              <select
                className="output-mode-select"
                value={outputMode}
                onChange={(e) => setOutputMode(e.target.value)}
                title="输出模式"
              >
                <option value="markdown">Markdown</option>
                <option value="canvas">画布</option>
              </select>
            }
          />
        </div>

        <div className="split-handle" ref={splitRef} />

        <aside style={{ "--aside-width": splitPos + "px" } as React.CSSProperties}>
          {/* Canvas 全屏覆盖层 */}
      {canvasFullscreen && activeMsg?.response?.canvas_schema && (
        <CanvasViewer
          fullscreen
          schema={activeMsg.response.canvas_schema}
          enrichedMarkdown={activeMsg.response.enriched_markdown}
          findings={activeMsg.response.audit_metadata.findings}
          sessionId={activeMsg.response.session_id}
          onVerify={async () => {
            try {
              const result = await verifySessionSimple(activeMsg.response!.session_id);
              setVerifyResult(result);
            } catch (err) {
              setError(err instanceof Error ? err.message : "Verification failed");
            }
          }}
          onExitFullscreen={() => {
            setCanvasFullscreen(false);
            setActiveMsg(null);
          }}
        />
      )}

      {activeMsg && activeMsg.response && !canvasFullscreen ? (
            <>
              {activeMsg.response.canvas_schema && (
                <div className="sidebar-tabs">
                  <button
                    className={`sidebar-tab ${sidebarTab === "audit" ? "active" : ""}`}
                    onClick={() => setSidebarTab("audit")}
                  >
                    审计
                  </button>
                  <button
                    className={`sidebar-tab ${sidebarTab === "canvas" ? "active" : ""}`}
                    onClick={() => setSidebarTab("canvas")}
                  >
                    画布
                  </button>
                </div>
              )}
              {sidebarTab === "canvas" && activeMsg.response.canvas_schema ? (
                <CanvasViewer
                  schema={activeMsg.response.canvas_schema}
                  enrichedMarkdown={activeMsg.response.enriched_markdown}
                  findings={activeMsg.response.audit_metadata.findings}
                  sessionId={activeMsg.response.session_id}
                  onVerify={async () => {
                    try {
                      const result = await verifySessionSimple(activeMsg.response!.session_id);
                      setVerifyResult(result);
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Verification failed");
                    }
                  }}
                  onProvenanceClick={(findingIds) => {
                    // Canvas → Audit 联动：切换到审计标签并高亮第一个 Finding
                    setSidebarTab("audit");
                    setHighlightedFindingId(findingIds[0] || null);
                  }}
                />
              ) : activeMsg.response.canvas_schema ? (
                // 画布模式下审计标签：直接渲染 Markdown，无打字机效果
                <div className="markdown-overlay">
                  <div className="markdown-overlay-header">
                    <h3>分析报告</h3>
                    <button onClick={() => setActiveMsg(null)} className="close-btn">✕</button>
                  </div>
                  <div className="markdown-overlay-content">
                    <MarkdownRenderer content={activeMsg.response.enriched_markdown || activeMsg.response.markdown_content} />
                  </div>
                </div>
              ) : (
                <MarkdownOverlay
                  key={activeMsg.id}
                  content={activeMsg.response.markdown_content}
                  animate={animatingId === activeMsg.id && !viewedIds.current.has(activeMsg.id)}
                  onAnimated={() => {
                    setAnimatingId(null);
                    viewedIds.current.add(activeMsg.id);
                  }}
                  onClose={() => setActiveMsg(null)}
                />
              )}
            </>
          ) : auditTarget && auditTarget.response ? (
            <>
              <AuditPanel
                response={auditTarget.response}
                totalTokensAll={totalTokensAll}
                highlightedFindingId={highlightedFindingId}
                onFindingFocus={(findingId) => {
                  // Audit → Canvas 联动：切换到画布标签
                  setSidebarTab("canvas");
                  setHighlightedFindingId(findingId);
                }}
                versions={versions}
                onVerify={async () => {
                  try {
                    const result = await verifySessionSimple(auditTarget.response!.session_id);
                    setVerifyResult(result);
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Verification failed");
                  }
                }}
                rollbackable={auditTarget.response.rollback_options.rollbackable_findings}
                onRollback={rollback}
              />
            </>
          ) : (
            <div className="empty">👈 左侧输入分析任务并提交后，审计元数据和回退控件将在此展示</div>
          )}

          {/* 验证弹窗 */}
          {verifyResult && (
            <VerificationModal
              result={verifyResult}
              onClose={() => setVerifyResult(null)}
            />
          )}
        </aside>
      </section>
    </main>
  );
}

/* ── localStorage 持久化辅助函数 ── */

const DEFAULT_LLM: LlmConfig = { provider: "chatgpt", model: "gpt-4o-mini", api_key: "" };
const DEFAULT_AGENT: PerAgentLlm = {
  research: { ...DEFAULT_LLM },
  verification: { ...DEFAULT_LLM },
  synthesis: { ...DEFAULT_LLM },
};

/** 从 localStorage 加载 LLM 配置 */
function loadLlmConfig(): LlmConfig {
  try {
    const raw = localStorage.getItem("sg_llm");
    return raw ? { ...DEFAULT_LLM, ...JSON.parse(raw) } : { ...DEFAULT_LLM };
  } catch { return { ...DEFAULT_LLM }; }
}

/** 保存 LLM 配置到 localStorage */
function saveLlmConfig(cfg: LlmConfig) {
  try { localStorage.setItem("sg_llm", JSON.stringify(cfg)); } catch {}
}

/** 从 localStorage 加载 Agent LLM 配置 */
function loadAgentLlm(): PerAgentLlm {
  try {
    const raw = localStorage.getItem("sg_agent_llm");
    if (!raw) return { ...DEFAULT_AGENT };
    const parsed = JSON.parse(raw);
    return {
      research: { ...DEFAULT_LLM, ...(parsed.research || {}) },
      verification: { ...DEFAULT_LLM, ...(parsed.verification || {}) },
      synthesis: { ...DEFAULT_LLM, ...(parsed.synthesis || {}) },
    };
  } catch { return { ...DEFAULT_AGENT }; }
}

/** 保存 Agent LLM 配置到 localStorage */
function saveAgentLlm(cfg: PerAgentLlm) {
  try { localStorage.setItem("sg_agent_llm", JSON.stringify(cfg)); } catch {}
}

/** 从 localStorage 加载消息历史 */
function loadMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem("sg_messages");
    if (!raw) return [];
    return JSON.parse(raw) as ChatMessage[];
  } catch { return []; }
}

/** 保存消息历史到 localStorage（最多保留 20 条） */
function saveMessages(msgs: ChatMessage[]) {
  try {
    const trimmed = msgs.slice(-20);
    localStorage.setItem("sg_messages", JSON.stringify(trimmed));
  } catch {}
}

/** 睡眠辅助函数 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 从 localStorage 加载 Agent 锁定状态 */
function lockedFromStorage(agent: string): boolean {
  try {
    const raw = localStorage.getItem("sg_agent_locks");
    if (!raw) return true;
    const parsed = JSON.parse(raw);
    return parsed[agent] ?? true;
  } catch { return true; }
}

createRoot(document.getElementById("root")!).render(
  <App />
);