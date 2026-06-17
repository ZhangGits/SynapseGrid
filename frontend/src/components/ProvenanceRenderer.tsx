import React, { useState, useCallback } from "react";
import type { Finding } from "../types";

/**
 * Provenance 渲染器 — 渲染带 provenance 标签的增强 Markdown
 *
 * 负责：
 * 1. 解析 enriched_markdown 中的 <provenance>、<data>、<conflict> 标签
 * 2. 将标签渲染为可交互的 React 组件
 * 3. 支持点击 provenance 标签时内联展开证据卡片
 * 4. 支持点击 provenance 标签时触发回调（用于 Canvas → Audit 联动）
 *
 * 标签规范：
 * - <provenance finding="f1,f2">文本</provenance> → 可点击下划线 + 🔍 角标，点击展开内联证据
 * - <data value="45.2" type="percentage">45.2%</data> → 高亮数字
 * - <conflict id="c1" between="f2,f3">文本</conflict> → 警告色边框卡片
 */
interface Props {
  /** 带 provenance 标签的增强 Markdown 内容 */
  content: string;
  /** 分析要点列表（用于内联展开证据） */
  findings?: Finding[];
  /** 点击 provenance 标签时的回调（用于 Canvas → Audit 联动） */
  onProvenanceClick?: (findingIds: string[]) => void;
}

/**
 * 提取 Markdown 中的标题列表，用于生成章节导航
 *
 * @param markdown - Markdown 内容
 * @returns 标题列表，每项包含级别和文本
 */
export function extractOutline(markdown: string): { level: number; text: string; id: string }[] {
  const lines = markdown.split("\n");
  const outline: { level: number; text: string; id: string }[] = [];
  const seen = new Set<string>();

  for (const line of lines) {
    const match = line.match(/^(#{1,3})\s+(.+)$/);
    if (match) {
      const level = match[1].length;
      const text = match[2].trim().replace(/<[^>]+>/g, ""); // 去掉 HTML 标签
      let id = text.toLowerCase().replace(/\s+/g, "-").replace(/[^\w\-]/g, "");
      // 去重：相同 ID 加序号
      let uniqueId = id;
      let counter = 1;
      while (seen.has(uniqueId)) {
        uniqueId = `${id}-${counter++}`;
      }
      seen.add(uniqueId);
      outline.push({ level, text, id: uniqueId });
    }
  }
  return outline;
}

/**
 * 给 Markdown 中的标题添加锚点 ID，用于章节导航跳转
 *
 * @param markdown - 原始 Markdown
 * @param outline - 标题列表
 * @returns 带锚点的 Markdown
 */
export function addHeadingAnchors(
  markdown: string,
  outline: { level: number; text: string; id: string }[]
): string {
  let idx = 0;
  return markdown.replace(/^(#{1,3})\s+(.+)$/gm, (match, hashes, text) => {
    const item = outline[idx++];
    if (item) {
      return `${hashes} <span id="${item.id}">${text.trim()}</span>`;
    }
    return match;
  });
}

/**
 * ProvenanceRenderer 组件
 *
 * 将 enriched_markdown 中的 HTML 标签解析为交互式 React 元素。
 * 使用正则表达式分步解析，支持嵌套 Markdown 内容。
 */
export function ProvenanceRenderer({ content, findings, onProvenanceClick }: Props) {
  /** 当前展开的 provenance finding ID */
  const [expandedId, setExpandedId] = useState<string | null>(null);

  /** 查找 finding 详情 */
  const getFinding = useCallback(
    (id: string): Finding | undefined => findings?.find((f) => f.id === id),
    [findings]
  );

  /** 置信度颜色 */
  function confidenceColor(confidence: number): string {
    if (confidence >= 0.8) return "#22c55e";
    if (confidence >= 0.6) return "#eab308";
    return "#ef4444";
  }

  // 第一步：解析 <conflict> 标签
  const afterConflict = content.replace(
    /<conflict\s+id="([^"]*)"\s+between="([^"]*)"\s*>([\s\S]*?)<\/conflict>/g,
    (_, id, between, text) => {
      const betweenIds = between.split(",").map((s: string) => s.trim());
      return `<div class="provenance-conflict" data-conflict-id="${id}" data-between="${betweenIds.join(",")}">
        <span class="provenance-conflict-icon">⚠️</span>
        <span class="provenance-conflict-text">${text}</span>
      </div>`;
    }
  );

  // 第二步：解析 <data> 标签
  const afterData = afterConflict.replace(
    /<data\s+value="([^"]*)"\s+type="([^"]*)"\s*>([\s\S]*?)<\/data>/g,
    (_, value, type, text) => {
      return `<span class="provenance-data" data-value="${value}" data-type="${type}" title="类型: ${type}, 原始值: ${value}">${text}</span>`;
    }
  );

  // 第三步：解析 <provenance> 标签，插入 data-finding 属性用于点击识别
  const afterProvenance = afterData.replace(
    /<provenance\s+finding="([^"]*)"\s*>([\s\S]*?)<\/provenance>/g,
    (_, finding, text) => {
      const findingIds = finding.split(",").map((s: string) => s.trim());
      return `<span class="provenance-link" data-finding="${findingIds.join(",")}" data-finding-id="${findingIds[0] || ""}">
        ${text}<sup class="provenance-sup">🔍</sup>
      </span>`;
    }
  );

  /** 处理点击事件：展开/收起证据卡片或触发联动 */
  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const link = target.closest(".provenance-link") as HTMLElement | null;
    if (!link) return;

    const findingAttr = link.getAttribute("data-finding");
    if (!findingAttr) return;

    const findingIds = findingAttr.split(",").map((s) => s.trim());
    const primaryId = findingIds[0] || "";

    // 如果已展开，则收起；否则展开
    setExpandedId((prev) => (prev === primaryId ? null : primaryId));

    // 同时触发外部回调（Canvas → Audit 联动）
    if (onProvenanceClick) {
      onProvenanceClick(findingIds);
    }
  };

  // 获取当前展开的 finding 详情
  const expandedFinding = expandedId ? getFinding(expandedId) : null;

  return (
    <div className="provenance-renderer-wrapper">
      <div
        className="provenance-renderer"
        onClick={handleClick}
        dangerouslySetInnerHTML={{ __html: afterProvenance }}
      />
      {/* 内联证据展开卡片 */}
      {expandedFinding && (
        <div className="provenance-inline-card">
          <div className="provenance-inline-header">
            <span className="provenance-inline-id">{expandedFinding.id}</span>
            <span
              className="provenance-inline-confidence"
              style={{ color: confidenceColor(expandedFinding.confidence) }}
            >
              {(expandedFinding.confidence * 100).toFixed(0)}% 置信度
            </span>
            <button
              className="provenance-inline-close"
              onClick={() => setExpandedId(null)}
              title="收起"
            >
              ✕
            </button>
          </div>
          <div className="provenance-inline-claim">
            <strong>观点：</strong>
            {expandedFinding.claim}
          </div>
          <div className="provenance-inline-evidence">
            <strong>论据：</strong>
            {expandedFinding.evidence}
          </div>
          {expandedFinding.source && (
            <div className="provenance-inline-source">
              <strong>来源：</strong>
              {expandedFinding.source}
            </div>
          )}
        </div>
      )}
    </div>
  );
}