/**
 * Markdown 渲染器组件 — 将 Markdown 文本渲染为 HTML
 *
 * 使用 react-markdown 库渲染 Markdown 内容。
 * 支持标准的 Markdown 语法（标题、列表、代码块等）。
 */

import ReactMarkdown from "react-markdown";

interface Props {
  content: string;
}

export function MarkdownRenderer({ content }: Props) {
  return (
    <div className="markdown-renderer">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}
