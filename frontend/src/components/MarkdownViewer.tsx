/**
 * Markdown 查看器组件 — 简单的 Markdown 显示组件
 *
 * 与 MarkdownRenderer 功能相同，提供独立的查看器组件。
 */

import { MarkdownRenderer } from "./MarkdownRenderer";

interface Props {
  content: string;
}

export function MarkdownViewer({ content }: Props) {
  return (
    <div className="markdown-viewer">
      <MarkdownRenderer content={content} />
    </div>
  );
}
