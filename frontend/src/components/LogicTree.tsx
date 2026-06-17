 /**
  * LogicTree 组件 — 使用 Cytoscape.js + dagre 渲染论证结构树
  *
  * 支持两种显示模式：
  * 1. 自适应模式（侧边栏）：cy.fit() 自动适应容器
  * 2. 滚动模式（全屏）：固定 zoom=1，容器随内容扩展，通过滚动条浏览
  *
  * 新增特性：
  * - 节点标签显示摘要（优先使用 Synthesis Agent 提取的 summary 字段，否则句末截断 + 换行）
  * - 完整内容在弹窗中展示
  * - 左下角全局缩略图（minimap），实时同步大图画布视口
  * - 节点拖拽后缩略图自动更新
  */
 import { useEffect, useRef, useCallback } from "react";
import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import type { LogicGraph } from "../types";

cytoscape.use(dagre);

interface Props {
  graph: LogicGraph;
  onNodeClick?: (nodeId: string) => void;
  highlightedNodeId?: string | null;
  displayMode?: "fit" | "scroll";
}

const NODE_SHAPE: Record<string, string> = {
  question: "diamond",
  conclusion: "round-rectangle",
  claim: "round-rectangle",
  evidence: "ellipse",
};

const EDGE_STYLE: Record<string, { lineStyle: string; color: string; width: number }> = {
  supports: { lineStyle: "solid", color: "#94a3b8", width: 2 },
  perspective_difference: { lineStyle: "dashed", color: "#3b82f6", width: 2 },
  tension: { lineStyle: "dashed", color: "#f59e0b", width: 2 },
  genuine_contradiction: { lineStyle: "dashed", color: "#ef4444", width: 3 },
};

function credBorder(cred: number): string {
  if (cred >= 0.8) return "#22c55e";
  if (cred < 0.6) return "#f59e0b";
  return "#94a3b8";
}

/** dagre 布局参数 */
const DAGRE_CONFIG = {
  name: "dagre",
  rankDir: "TB",
  rankSep: 180,
  nodeSep: 120,
  edgeSep: 80,
  padding: 80,
  nodeDimensionsIncludeLabels: true,
} as const;

/** 生成节点摘要：优先在句末/逗号处截断，否则在 maxChars 处截断 */
function makeSummary(text: string, maxChars: number = 40): string {
  if (!text || text.length <= maxChars) return text;
  const punctuations = /[。！？.!?;；，,]/;
  let bestCut = maxChars;
  for (let i = maxChars; i > maxChars * 0.4; i--) {
    if (punctuations.test(text[i])) {
      bestCut = i + 1;
      break;
    }
  }
  const cut = text.slice(0, bestCut).trim();
  return cut.length < text.length ? cut + "..." : cut;
}

/** 按固定字符数换行，用于 Cytoscape label（\n 强制换行） */
function wrapText(text: string, charsPerLine: number): string {
  if (text.length <= charsPerLine) return text;
  const lines: string[] = [];
  for (let i = 0; i < text.length; i += charsPerLine) {
    lines.push(text.slice(i, i + charsPerLine));
  }
  return lines.join("\n");
}

/** 向上查找第一个 overflow:auto/scroll 的祖先元素 */
function findScrollParent(el: HTMLElement): HTMLElement | null {
  let parent = el.parentElement;
  while (parent) {
    const style = window.getComputedStyle(parent);
    if (
      style.overflow === "auto" ||
      style.overflow === "scroll" ||
      style.overflowX === "auto" ||
      style.overflowX === "scroll" ||
      style.overflowY === "auto" ||
      style.overflowY === "scroll"
    ) {
      return parent;
    }
    parent = parent.parentElement;
  }
  return null;
}

export function LogicTree({ graph, onNodeClick, highlightedNodeId, displayMode = "fit" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const minimapRef = useRef<HTMLCanvasElement | null>(null);
  const scrollParentRef = useRef<HTMLElement | null>(null);
  const panRef = useRef({ x: 0, y: 0 });
  const bbRef = useRef<{ x1: number; y1: number; w: number; h: number } | null>(null);

  /** 绘制缩略图 */
  const drawMinimap = useCallback(() => {
    const cy = cyRef.current;
    const canvas = minimapRef.current;
    if (!cy || !canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const nodes = cy.nodes();
    if (nodes.length === 0) return;

    // 实时计算当前所有节点的 bounding box（不依赖缓存的 bbRef）
    const bb = nodes.boundingBox();
    const padding = 60;
    const graphW = Math.max(bb.w + padding * 2, 1);
    const graphH = Math.max(bb.h + padding * 2, 1);

    const w = canvas.width;
    const h = canvas.height;
    const scale = Math.min(w / graphW, h / graphH);

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgba(15, 23, 42, 0.92)";
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "rgba(148, 163, 184, 0.3)";
    ctx.lineWidth = 1;
    ctx.strokeRect(0, 0, w, h);

    // 绘制边（细线）
    cy.edges().forEach((edge) => {
      const src = edge.source().position();
      const tgt = edge.target().position();
      const sx = (src.x - bb.x1 + padding) * scale;
      const sy = (src.y - bb.y1 + padding) * scale;
      const tx = (tgt.x - bb.x1 + padding) * scale;
      const ty = (tgt.y - bb.y1 + padding) * scale;
      ctx.strokeStyle = "rgba(148, 163, 184, 0.25)";
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(tx, ty);
      ctx.stroke();
    });

    // 绘制节点（彩色小圆点）
    nodes.forEach((n) => {
      const pos = n.position();
      const x = (pos.x - bb.x1 + padding) * scale;
      const y = (pos.y - bb.y1 + padding) * scale;
      const type = n.data("type");
      ctx.fillStyle =
        type === "question" ? "#f59e0b" :
        type === "conclusion" ? "#3b82f6" :
        type === "claim" ? "#22c55e" : "#94a3b8";
      ctx.beginPath();
      ctx.arc(x, y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    });

    // 计算当前视口在 model 坐标系中的范围
    let vModelX1: number, vModelY1: number, vModelW: number, vModelH: number;

    if (displayMode === "scroll" && scrollParentRef.current) {
      const sp = scrollParentRef.current;
      // 直接读取 cytoscape 当前的 pan（避免 panRef 缓存过时）
      const pan = cy.pan();
      // 容器坐标 = model 坐标 * zoom + pan
      // scrollLeft/Top 是容器坐标系中的可见偏移
      // => model 坐标 = (scrollLeft/Top - pan) / zoom
      const zoom = cy.zoom();
      vModelX1 = (sp.scrollLeft - pan.x) / zoom;
      vModelY1 = (sp.scrollTop - pan.y) / zoom;
      vModelW = sp.clientWidth / zoom;
      vModelH = sp.clientHeight / zoom;
    } else {
      const extent = cy.extent();
      vModelX1 = extent.x1;
      vModelY1 = extent.y1;
      vModelW = (extent as any).w ?? (extent.x2 - extent.x1);
      vModelH = (extent as any).h ?? (extent.y2 - extent.y1);
    }

    const vx = (vModelX1 - bb.x1 + padding) * scale;
    const vy = (vModelY1 - bb.y1 + padding) * scale;
    const vw = vModelW * scale;
    const vh = vModelH * scale;

    // 精确裁剪：绿框的四条边都必须正确
    const drawX = Math.max(0, Math.min(w, vx));
    const drawY = Math.max(0, Math.min(h, vy));
    const drawX2 = Math.max(0, Math.min(w, vx + vw));
    const drawY2 = Math.max(0, Math.min(h, vy + vh));
    const drawW = drawX2 - drawX;
    const drawH = drawY2 - drawY;

    if (drawW > 0 && drawH > 0) {
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(drawX, drawY, drawW, drawH);
    }
  }, [displayMode]);

  useEffect(() => {
    if (!containerRef.current || !graph || !graph.nodes?.length) return;

    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }

    const container = containerRef.current;

    // 记录滚动容器引用（滚动模式下使用）
    scrollParentRef.current = findScrollParent(container);

    const elements: cytoscape.ElementDefinition[] = [];

    for (const node of graph.nodes) {
      const shape = NODE_SHAPE[node.type] || "ellipse";
      const opacity = node.rolled_back ? 0.3 : 1;
      const borderColor = credBorder(node.credibility);
      const fontSize = node.type === "question" || node.type === "conclusion" ? 20 : 16;
      const fontWeight = node.type === "question" || node.type === "conclusion" ? "bold" : "normal";
      const bgColor =
        node.type === "question" ? "#1e293b" :
        node.type === "conclusion" ? "#1e3a5f" :
        node.type === "claim" ? "#1e293b" : "#1a2a1a";

      // 优先使用 Synthesis Agent 生成的摘要，否则用本地截断
      const displayText = (node as any).summary || makeSummary(node.label, 40);
      const charsPerLine = node.type === "question" ? 12 : 14;
      const wrappedLabel = wrapText(displayText, charsPerLine);
      const lineCount = wrappedLabel.split("\n").length;

      // 动态计算节点尺寸
      const lineHeight = fontSize * 1.35;
      const nodeHeight = Math.max(55, lineCount * lineHeight + 20);
      const nodeWidth = node.type === "question" ? 200 : 260;

      elements.push({
        data: {
          id: node.id,
          label: wrappedLabel,
          full_label: node.label,
          summary: (node as any).summary || "",
          finding_id: node.finding_id,
          credibility: node.credibility,
          type: node.type,
          rolled_back: node.rolled_back,
        },
        style: {
          shape,
          "background-color": bgColor,
          "border-color": borderColor,
          "border-width": 3,
          "border-opacity": opacity,
          opacity,
          color: "#f1f5f9",
          "font-size": fontSize,
          "font-weight": fontWeight,
          "text-wrap": "wrap",
          "text-max-width": `${nodeWidth - 24}px`,
          "text-valign": "center",
          "text-halign": "center",
          width: nodeWidth,
          height: nodeHeight,
          "text-decoration": node.rolled_back ? "line-through" : "none",
        } as any,
      });
    }

    for (const edge of graph.edges) {
      const style = EDGE_STYLE[edge.type] || EDGE_STYLE.supports;
      elements.push({
        data: {
          id: `${edge.from_id}_${edge.to_id}`,
          source: edge.from_id,
          target: edge.to_id,
          type: edge.type,
          description: edge.description || "",
        },
        style: {
          "line-style": style.lineStyle,
          "line-color": style.color,
          "target-arrow-color": style.color,
          "target-arrow-shape": "triangle",
          width: style.width,
          "curve-style": "bezier",
        } as any,
      });
    }

    try {
      if (displayMode === "scroll") {
        container.style.width = "5000px";
        container.style.height = "5000px";
      }

      const cy = cytoscape({
        container,
        elements,
        style: [
          {
            selector: "node",
            style: { label: "data(label)" },
          },
          {
            selector: "edge",
            style: {
              label: "data(description)",
              "font-size": 13,
              color: "#94a3b8",
              "text-wrap": "wrap",
              "text-max-width": "180px",
              "text-background-color": "#1e293b",
              "text-background-opacity": 0.95,
              "text-background-padding": 3,
              "text-background-shape": "roundrectangle",
            },
          },
          {
            selector: ".highlighted",
            style: {
              "border-width": 5,
              "border-color": "#3b82f6",
              "background-color": "#1e3a8a",
            } as any,
          },
        ],
        wheelSensitivity: 0.2,
        minZoom: 0.2,
        maxZoom: 3,
      });

      cy.on("tap", "node", (evt: cytoscape.EventObject) => {
        const node = evt.target as cytoscape.NodeSingular;
        if (onNodeClick) onNodeClick(node.data("id"));
      });

      cy.on("mouseover", "edge", (evt: cytoscape.EventObject) => {
        const edge = evt.target as cytoscape.EdgeSingular;
        const desc = edge.data("description");
        if (desc) {
          const tip = document.createElement("div");
          tip.className = "cy-tooltip";
          tip.textContent = desc;
          tip.style.cssText =
            "position:fixed; background:#1e293b; color:#f1f5f9; padding:8px 12px; border-radius:6px; font-size:0.9rem; pointer-events:none; z-index:9999; border:1px solid #334155; max-width:300px;";
          document.body.appendChild(tip);
          const updatePos = (e: MouseEvent) => {
            tip.style.left = e.clientX + 14 + "px";
            tip.style.top = e.clientY - 12 + "px";
          };
          updatePos(evt.originalEvent as MouseEvent);
          const moveHandler = (e: cytoscape.EventObject) => {
            updatePos(e.originalEvent as MouseEvent);
          };
          cy.on("mousemove", "edge", moveHandler);
          cy.one("mouseout", "edge", () => {
            tip.remove();
            cy.off("mousemove", "edge", moveHandler);
          });
        }
      });

      // 节点拖拽结束后更新缩略图（drawMinimap 内部会实时计算 nodes.boundingBox()）
      cy.on("dragfree", drawMinimap);

      // 监听 cytoscape 的 pan/zoom（滚轮平移或缩放时同步绿框）
      cy.on("pan zoom", drawMinimap);

      cyRef.current = cy;

      if (displayMode === "scroll") {
        const layout = cy.layout({ ...DAGRE_CONFIG, fit: false, animate: false } as cytoscape.LayoutOptions);

        layout.on("layoutstop", () => {
          const bb = cy.nodes().boundingBox();
          const padding = 100;

          // 容器尺寸额外增加边距（用于容纳边标签和空白区域）
          const containerMaxX = bb.x2 + 120;
          const containerMaxY = bb.y2 + 80;
          const contentW = containerMaxX - bb.x1 + padding * 2;
          const contentH = containerMaxY - bb.y1 + padding * 2;

          const finalW = Math.max(window.innerWidth - 40, contentW);
          const finalH = Math.max(window.innerHeight - 120, contentH);

          container.style.width = `${finalW}px`;
          container.style.height = `${finalH}px`;

          cy.resize();
          cy.zoom(1);
          const panX = padding - bb.x1;
          const panY = padding - bb.y1;
          cy.pan({ x: panX, y: panY });

          panRef.current = { x: panX, y: panY };

          // 滚动模式下监听 HTML 滚动
          const sp = scrollParentRef.current;
          if (sp) {
            sp.addEventListener("scroll", drawMinimap);
          }

          drawMinimap();
        });

        layout.run();
      } else {
        cy.layout({ ...DAGRE_CONFIG, fit: true, padding: 60 } as cytoscape.LayoutOptions).run();
        const nodes = cy.nodes();
        const bb = nodes.boundingBox();
        bbRef.current = { x1: bb.x1, y1: bb.y1, w: bb.w, h: bb.h };
        setTimeout(drawMinimap, 350);
      }
    } catch (err) {
      console.error("Cytoscape init failed:", err);
    }

    return () => {
      const sp = scrollParentRef.current;
      if (sp) {
        sp.removeEventListener("scroll", drawMinimap);
      }
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
    };
  }, [graph, onNodeClick, displayMode, drawMinimap]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !highlightedNodeId) return;
    cy.nodes().removeClass("highlighted");
    const target = cy.getElementById(highlightedNodeId);
    if (target?.length) {
      target.addClass("highlighted");
      cy.animate({ center: { eles: target }, zoom: 1.2 }, { duration: 400 });
    }
  }, [highlightedNodeId]);

  if (!graph || !graph.nodes?.length) {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          minHeight: 300,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#94a3b8",
        }}
      >
        无论证结构数据
      </div>
    );
  }

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", minHeight: 300 }}>
      <div
        ref={containerRef}
        style={{
          width: "100%",
          height: "100%",
          minHeight: 300,
        }}
      />
      <canvas
        ref={minimapRef}
        width={200}
        height={140}
        style={{
          position: "absolute",
          bottom: 12,
          left: 12,
          width: 200,
          height: 140,
          borderRadius: 8,
          border: "1px solid rgba(148, 163, 184, 0.3)",
          pointerEvents: "none",
          zIndex: 10,
        }}
      />
    </div>
  );
}