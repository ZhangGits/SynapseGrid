/**
 * NarrativePane 组件 — 渲染增强 Markdown 并支持与 LogicTree 双向联动
 *
 * Phase 4 v4.0: 将 enriched_markdown 渲染为交互式叙事段落。
 */

import { useRef, useEffect, useImperativeHandle, forwardRef, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import type { Finding, LogicNode } from "../types";

interface Props {
  enrichedMarkdown: string;
  findings?: Finding[];
  logicNodes?: LogicNode[];
  highlightedParagraphId?: string | null;
  onProvenanceClick?: (findingIds: string[]) => void;
}

function credColor(c: number): string {
  if (c >= 0.8) return "#22c55e";
  if (c >= 0.6) return "#eab308";
  return "#ef4444";
}

export const NarrativePane = forwardRef(function NarrativePane(
  { enrichedMarkdown, findings, logicNodes, highlightedParagraphId, onProvenanceClick }: Props,
  ref: React.Ref<{ scrollToParagraph: (nodeId: string) => void }>
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [expandedFindingId, setExpandedFindingId] = useState<string | null>(null);

  const getFinding = useCallback(
    (id: string) => findings?.find((f) => f.id === id),
    [findings]
  );

  useImperativeHandle(ref, () => ({
    scrollToParagraph(nodeId: string) {
      const el = document.getElementById(`paragraph-${nodeId}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("narrative-highlight");
        setTimeout(() => el.classList.remove("narrative-highlight"), 2000);
      }
    },
  }));

  useEffect(() => {
    if (highlightedParagraphId) {
      const el = document.getElementById(`paragraph-${highlightedParagraphId}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("narrative-highlight");
        setTimeout(() => el.classList.remove("narrative-highlight"), 2000);
      }
    }
  }, [highlightedParagraphId]);

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const link = target.closest(".provenance-link") as HTMLElement | null;
    if (!link) return;
    const findingAttr = link.getAttribute("data-finding");
    if (!findingAttr) return;
    const findingIds = findingAttr.split(",").map((s: string) => s.trim());
    const primaryId = findingIds[0] || "";
    setExpandedFindingId((prev) => (prev === primaryId ? null : primaryId));
    if (onProvenanceClick) onProvenanceClick(findingIds);
  };

  const expandedFinding = expandedFindingId ? getFinding(expandedFindingId) : null;

  // 预处理 Markdown：
  // 1. 在 provenance 标签前插入段落锚点
  // 2. 将 <provenance> 转为可点击 <span>
  // 3. 剥离内部 <finding> 标签（只保留内容）
  let processed = enrichedMarkdown;

  // Step 1: 插入段落锚点
  if (logicNodes) {
    for (const n of logicNodes) {
      if (n.finding_id) {
        const pattern = new RegExp(
          `(<provenance[^>]*finding="[^"]*${n.finding_id}[^"]*"[^>]*>)`, "g"
        );
        if (!processed.match(pattern)) continue;
        processed = processed.replace(
          pattern,
          `<span id="paragraph-${n.id}"></span>$1`
        );
      }
    }
  }

  // Step 2: 将 provenance 标签包装为可点击 span
  processed = processed
    .replace(
      /<provenance\s+finding="([^"]*)"\s+credibility="([^"]*)"\s*>/g,
      (_: string, finding: string, _cred: string) =>
        `<span class="provenance-link" data-finding="${finding}" style="cursor:pointer;border-bottom:1px dashed #3b82f6;">`
    )
    .replace(/<\/provenance>/g, "</span>");

  // Step 3: 剥离 <finding> 标签（只保留内容，去除标签本身）
  // <finding id="..." confidence="...">内容</finding> → 内容
  processed = processed
    .replace(/<finding\s+[^>]*>/g, "")
    .replace(/<\/finding>/g, "");

  return (
    <div className="narrative-pane" ref={containerRef} onClick={handleClick}>
      <div className="narrative-header">
        <h4>叙事区</h4>
        <span className="narrative-hint">
          点击 <span className="provenance-link-demo">下划线文本</span> 查看证据详情
        </span>
      </div>
      <div className="narrative-content">
        <ReactMarkdown>{processed}</ReactMarkdown>
      </div>
      {expandedFinding && (
        <div className="narrative-inline-card">
          <div className="narrative-inline-header">
            <span className="narrative-inline-id">{expandedFinding.id}</span>
            <span className="narrative-inline-confidence" style={{ color: credColor(expandedFinding.confidence) }}>
              {(expandedFinding.confidence * 100).toFixed(0)}% 置信度
            </span>
            <button className="narrative-inline-close" onClick={() => setExpandedFindingId(null)}>✕</button>
          </div>
          <div className="narrative-inline-claim"><strong>观点：</strong>{expandedFinding.claim}</div>
          <div className="narrative-inline-evidence"><strong>论据：</strong>{expandedFinding.evidence}</div>
          {expandedFinding.source && (
            <div className="narrative-inline-source"><strong>来源：</strong>{expandedFinding.source}</div>
          )}
        </div>
      )}
    </div>
  );
});