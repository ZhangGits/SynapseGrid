/**
 * Agent 分析节点可视化组件
 *
 * 根据输出模式展示不同数量的分析节点：
 * - Markdown 模式：Research（研究）、Verification（验证）
 * - Canvas 模式：Research（研究）、Verification（验证）、Synthesis（综合）
 *
 * 每个节点用彩色圆圈表示，分析时旋转，完成后高亮。
 * 支持通过 completedStages 实时更新每个节点的完成状态。
 */
import { useEffect, useState } from "react";

interface Props {
  /** 输出模式：markdown 或 canvas */
  outputMode: string;
  /** 是否正在加载（分析中） */
  loading: boolean;
  /** 已完成的阶段列表（来自后端实时进度） */
  completedStages?: string[];
}

interface NodeDef {
  key: string;
  label: string;
  color: string;
  glowColor: string;
}

const MARKDOWN_NODES: NodeDef[] = [
  { key: "research", label: "Research", color: "#3b82f6", glowColor: "rgba(59, 130, 246, 0.5)" },
  { key: "verification", label: "Verification", color: "#22c55e", glowColor: "rgba(34, 197, 94, 0.5)" },
];

const CANVAS_NODES: NodeDef[] = [
  { key: "research", label: "Research", color: "#3b82f6", glowColor: "rgba(59, 130, 246, 0.5)" },
  { key: "verification", label: "Verification", color: "#22c55e", glowColor: "rgba(34, 197, 94, 0.5)" },
  { key: "synthesis", label: "Synthesis", color: "#8b5cf6", glowColor: "rgba(139, 92, 246, 0.5)" },
];

/** 分析完成后的高亮持续时间(ms) */
const GLOW_DURATION = 1200;

export function AgentAnalysisNodes({ outputMode, loading, completedStages = [] }: Props) {
  const nodes = outputMode === "canvas" ? CANVAS_NODES : MARKDOWN_NODES;
  const [completedNodes, setCompletedNodes] = useState<Set<string>>(new Set());
  const [glowingNodes, setGlowingNodes] = useState<Set<string>>(new Set());

  // 根据 completedStages 实时更新节点完成状态
  useEffect(() => {
    const stages = new Set(completedStages);
    const newCompleted = new Set<string>();
    
    // research 完成
    if (stages.has("research")) {
      newCompleted.add("research");
    }
    // verification 完成
    if (stages.has("verification")) {
      newCompleted.add("verification");
    }
    // synthesis/post_processor 完成（canvas/markdown 最终阶段）
    if (stages.has("synthesis") || stages.has("post_processor")) {
      newCompleted.add("synthesis");
    }

    // 找出新完成的节点，触发高亮
    const newlyCompleted: string[] = [];
    newCompleted.forEach((key) => {
      if (!completedNodes.has(key)) {
        newlyCompleted.push(key);
      }
    });

    if (newlyCompleted.length > 0) {
      setCompletedNodes(newCompleted);
      setGlowingNodes((prev) => {
        const next = new Set(prev);
        newlyCompleted.forEach((k) => next.add(k));
        return next;
      });
      // 高亮持续一段时间后熄灭
      const glowTimer = window.setTimeout(() => {
        setGlowingNodes((prev) => {
          const next = new Set(prev);
          newlyCompleted.forEach((k) => next.delete(k));
          return next;
        });
      }, GLOW_DURATION);
      return () => clearTimeout(glowTimer);
    } else {
      setCompletedNodes(newCompleted);
    }
  }, [completedStages]);

  // 当 loading 结束时，如果所有节点都已完成但未标记，确保标记
  useEffect(() => {
    if (!loading) {
      const allCompleted = new Set(nodes.map((n) => n.key));
      setCompletedNodes(allCompleted);
    }
  }, [loading, nodes]);

  return (
    <div className="agent-analysis-nodes">
      <div className="agent-nodes-track">
        {nodes.map((node, index) => {
          const isCompleted = completedNodes.has(node.key);
          const isGlowing = glowingNodes.has(node.key);
          const isActive = loading && !isCompleted;
          return (
            <div key={node.key} className="agent-node-item">
              {/* 连接线与箭头（除第一个节点外） */}
              {index > 0 && (
                <div className="agent-node-connector">
                  <div
                    className={`agent-node-connector-line ${isCompleted ? "active" : ""}`}
                    style={{
                      background: isCompleted
                        ? nodes[index - 1].color
                        : "var(--border)",
                    }}
                  />
                  <div
                    className="agent-node-connector-arrow"
                    style={{
                      borderLeftColor: isCompleted ? node.color : "var(--border)",
                    }}
                  />
                </div>
              )}
              <div className="agent-node-content">
                <div
                  className={`agent-node-circle ${isActive ? "spinning" : ""} ${isCompleted ? "completed" : ""} ${isGlowing ? "glowing" : ""}`}
                  style={{
                    "--node-color": node.color,
                    "--node-glow": node.glowColor,
                  } as React.CSSProperties}
                >
                  {isCompleted ? "✓" : ""}
                </div>
                <span className={`agent-node-label ${isCompleted ? "completed" : ""}`}>
                  {node.label}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="agent-nodes-status">
        {loading
          ? "Multi-Agent Analysis in Progress..."
          : "Analysis Complete"}
      </div>
    </div>
  );
}