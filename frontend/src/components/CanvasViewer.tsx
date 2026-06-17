/**
 * CanvasViewer — LogicTree + NarrativePane dual layout (Phase 4 v4.0)
 *
 * 支持两种模式：
 * 1. 侧边栏模式（默认）：嵌入 aside 的分屏布局
 * 2. 全屏模式：占据整个视口，左上角有返回箭头
 *
 * 节点交互：点击节点 → 弹出详情浮层（显示对应 finding/节点的详细解释）
 */
import { useState, useCallback, useMemo, useEffect } from "react";
import { LogicTree } from "./LogicTree";
import { MarkdownRenderer } from "./MarkdownRenderer";
import type { LogicGraph, LogicNode, Finding } from "../types";

interface Props {
  schema?: LogicGraph | null;
  enrichedMarkdown?: string;
  findings?: Finding[];
  sessionId?: string;
  onVerify?: () => void;
  onProvenanceClick?: (findingIds: string[]) => void;
  /** 全屏模式开关 */
  fullscreen?: boolean;
  /** 退出全屏回调 */
  onExitFullscreen?: () => void;
}

type ViewMode = "structure" | "markdown";

function hasValidGraph(s: LogicGraph | null | undefined): boolean {
  return !!(s && s.nodes && s.nodes.length > 0);
}

/** 从 enrichedMarkdown 中提取与节点相关的段落文本 */
function extractNodeContext(
  node: LogicNode,
  enrichedMarkdown: string
): string {
  if (!node.finding_id) {
    // 对于 question/conclusion 等非 finding 节点，返回节点标签
    return `**${node.label}**\n\n类型: ${node.type}`;
  }

  // 查找 <provenance finding="...node.finding_id..."> 包裹的内容
  const pattern = new RegExp(
    `<provenance[^>]*finding="[^"]*${node.finding_id}[^"]*"[^>]*>([\\s\\S]*?)<\\/provenance>`,
    "i"
  );
  const match = enrichedMarkdown.match(pattern);
  if (match) {
    let text = match[1];

    // 去除所有 HTML/XML 标签（<finding>、自闭合标签等，支持跨行属性）
    text = text.replace(/<[^>]+>/g, "").trim();

    // 规范化 Markdown：在论点/论据等关键标记前添加换行，使结构清晰
    text = text
      .replace(/\s*(\*\*核心观点[：:]\*\*)\s*/g, "\n\n$1\n")
      .replace(/\s*(\*\*论据[：:]\*\*)\s*/g, "\n\n$1\n")
      .replace(/\s*(\*\*主要发现[：:]\*\*)\s*/g, "\n\n$1\n")
      .replace(/\s*(\*\*结论[：:]\*\*)\s*/g, "\n\n$1\n")
      .replace(/\s*(\*\*说明[：:]\*\*)\s*/g, "\n\n$1\n");

    return text.trim();
  }

  // 备选：直接在 markdown 中查找 finding id
  const lines = enrichedMarkdown.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(node.finding_id)) {
      // 收集该段落及后续几行
      return lines.slice(i, Math.min(i + 10, lines.length)).join("\n").trim();
    }
  }

  return `**${node.label}**\n\n未找到详细说明。`;
}

export function CanvasViewer(props: Props) {
  const {
    schema,
    enrichedMarkdown,
    findings,
    sessionId,
    onVerify,
    onProvenanceClick: _onProvenanceClick,
    fullscreen,
    onExitFullscreen,
  } = props;
  const [viewMode, setViewMode] = useState<ViewMode>("structure");
  const [highlightedNodeId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<LogicNode | null>(null);

  const handleNodeClick = useCallback((nodeId: string) => {
    if (!schema?.nodes) return;
    const node = schema.nodes.find((n) => n.id === nodeId);
    if (!node) return;

    setSelectedNode(node);
  }, [schema]);

  // 点击弹窗外部关闭弹窗（使用 document 级别监听，避免 cytoscape 事件冲突）
  useEffect(() => {
    if (!selectedNode) return;
    
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      // 点击弹窗内部：不处理
      if (target.closest(".node-detail-popup")) return;
      // 点击 cytoscape 画布内部：让 cytoscape tap 事件处理打开/切换
      if (target.closest(".logic-tree-container")) return;
      // 点击其他区域：关闭弹窗
      setSelectedNode(null);
    };
    
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [selectedNode]);

  // 计算弹窗内容
  const popupContent = useMemo(() => {
    if (!selectedNode || !enrichedMarkdown) return "";
    return extractNodeContext(selectedNode, enrichedMarkdown);
  }, [selectedNode, enrichedMarkdown]);

  // 查找 finding 详情
  const selectedFinding = useMemo(() => {
    if (!selectedNode?.finding_id || !findings) return null;
    return findings.find((f) => f.id === selectedNode.finding_id) || null;
  }, [selectedNode, findings]);

  // 关闭弹窗
  const closePopup = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // 全屏模式渲染
  if (fullscreen) {
    return (
      <div className="canvas-viewer canvas-fullscreen">
        {/* 左上角返回按钮 */}
        <button
          className="canvas-exit-fullscreen"
          onClick={(e) => {
            e.stopPropagation();
            onExitFullscreen?.();
          }}
          title="返回"
        >
          ← 返回
        </button>

        {/* 顶部标题栏 */}
        <div className="canvas-fullscreen-header">
          <h2>论证结构</h2>
          <div className="canvas-header-actions">
            <div className="canvas-view-tabs">
              <button
                className={"canvas-view-tab" + (viewMode === "structure" ? " active" : "")}
                onClick={() => setViewMode("structure")}
              >
                🗺️ 结构
              </button>
              <button
                className={"canvas-view-tab" + (viewMode === "markdown" ? " active" : "")}
                onClick={() => setViewMode("markdown")}
              >
                📄 Markdown
              </button>
            </div>
            {sessionId && onVerify && (
              <button className="verify-btn" onClick={onVerify} title="验证报告完整性">
                🔒 验证
              </button>
            )}
          </div>
        </div>

        {/* 全屏内容区 */}
        <div className="canvas-fullscreen-body">
          {viewMode === "markdown" ? (
            <div className="canvas-fullscreen-markdown">
              <MarkdownRenderer content={enrichedMarkdown || ""} />
            </div>
          ) : (
            <div className="canvas-fullscreen-tree-scroll">
              {hasValidGraph(schema) ? (
                <LogicTree
                  graph={schema!}
                  onNodeClick={handleNodeClick}
                  highlightedNodeId={highlightedNodeId}
                  displayMode="scroll"
                />
              ) : (
                <div className="canvas-no-graph">
                  当前为 Markdown 模式下生成的报告，无论证结构图。
                </div>
              )}
            </div>
          )}
        </div>

        {/* 节点详情弹窗 */}
        {selectedNode && (
          <div className="node-detail-popup" onClick={(e) => e.stopPropagation()}>
            <div className="node-detail-header">
              <span className="node-detail-type">{selectedNode.type}</span>
              <button className="node-detail-close" onClick={closePopup}>✕</button>
            </div>
            <div className="node-detail-body">
              {selectedFinding && (
                <div className="node-detail-meta">
                  <span className="node-detail-id">{selectedFinding.id}</span>
                  <span className="node-detail-confidence" style={{
                    color: selectedFinding.confidence >= 0.8 ? "#22c55e" :
                           selectedFinding.confidence >= 0.6 ? "#eab308" : "#ef4444"
                  }}>
                    {(selectedFinding.confidence * 100).toFixed(0)}% 置信度
                  </span>
                </div>
              )}
              <div className="node-detail-content">
                <MarkdownRenderer content={popupContent} />
              </div>
              {selectedFinding && (
                <div className="node-detail-footer">
                  {selectedFinding.evidence && (
                    <p><strong>论据：</strong>{selectedFinding.evidence}</p>
                  )}
                  {selectedFinding.source && (
                    <p><strong>来源：</strong>{selectedFinding.source}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // 侧边栏模式（默认）
  return (
    <div className="canvas-viewer" style={{ height: "100%", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <div className="canvas-header">
        <h3>论证结构</h3>
        <div className="canvas-header-actions">
          {hasValidGraph(schema) && (
            <div className="canvas-view-tabs">
              <button className={"canvas-view-tab" + (viewMode === "structure" ? " active" : "")} onClick={() => setViewMode("structure")}>
                🗺️ 结构
              </button>
              <button className={"canvas-view-tab" + (viewMode === "markdown" ? " active" : "")} onClick={() => setViewMode("markdown")}>
                📄 Markdown
              </button>
            </div>
          )}
          {sessionId && onVerify && (
            <button className="verify-btn" onClick={onVerify} title="验证报告完整性">🔒 验证</button>
          )}
        </div>
      </div>
      {body({ schema, enrichedMarkdown, viewMode, highlightedNodeId, handleNodeClick })}
    </div>
  );
}

function body({
  schema,
  enrichedMarkdown,
  viewMode,
  highlightedNodeId,
  handleNodeClick,
}: {
  schema?: LogicGraph | null;
  enrichedMarkdown?: string;
  viewMode: ViewMode;
  highlightedNodeId: string | null;
  handleNodeClick: (nodeId: string) => void;
}) {
  if (!hasValidGraph(schema)) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
        <div style={{ padding: 12, marginBottom: 16, background: "rgba(59,130,246,0.1)", borderRadius: 8, border: "1px solid rgba(59,130,246,0.3)", color: "var(--text)", fontSize: "0.85rem" }}>
          当前为 Markdown 模式下生成的报告，无论证结构图。如需查看论证结构，请使用<strong>画布模式</strong>重新提交任务。
        </div>
        {enrichedMarkdown && (
          <div style={{ padding: 16, background: "var(--bg-secondary)", borderRadius: 8, border: "1px solid var(--border)" }}>
            <h4 style={{ marginBottom: 12, marginTop: 0 }}>报告内容</h4>
            <MarkdownRenderer content={enrichedMarkdown} />
          </div>
        )}
      </div>
    );
  }

  if (viewMode === "markdown") {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: 16, background: "var(--bg-secondary)", borderRadius: 8, border: "1px solid var(--border)" }}>
        <MarkdownRenderer content={enrichedMarkdown || ""} />
      </div>
    );
  }

  return (
    <div className="canvas-split-layout">
      <div className="canvas-logic-tree-pane">
        <LogicTree graph={schema!} onNodeClick={handleNodeClick} highlightedNodeId={highlightedNodeId} />
      </div>
    </div>
  );
}