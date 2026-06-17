/**
 * 聊天输入组件 — 文本输入框和提交按钮
 *
 * 支持 Enter 提交（Shift+Enter 换行）。
 * 加载状态下禁用输入和按钮。
 */

import { useState, type KeyboardEvent, type ReactNode } from "react";

interface Props {
  loading: boolean;
  onSubmit: (text: string) => void;
  /** 可选的底部控件（如输出模式选择器），显示在提交按钮上方 */
  controls?: ReactNode;
}

export function ChatInput({ loading, onSubmit, controls }: Props) {
  const [text, setText] = useState("");

  /** 处理表单提交 */
  const handleSubmit = () => {
    const trimmed = text.trim();
    if (trimmed && !loading) {
      onSubmit(trimmed);
      setText("");
    }
  };

  /** 处理键盘事件：Enter 提交，Shift+Enter 换行 */
  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="chat-input">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入分析任务..."
        rows={3}
        disabled={loading}
      />
      <div className="chat-input-right">
        {controls && (
          <div className="chat-input-controls">
            {controls}
          </div>
        )}
        <button onClick={handleSubmit} disabled={loading || !text.trim()}>
          {loading ? "分析中..." : "提交"}
        </button>
      </div>
    </div>
  );
}
