/**
 * Markdown 覆盖层组件 — 带打字机动画的 Markdown 查看器
 *
 * 支持：
 * - 打字机动画效果（逐字显示）
 * - 关闭按钮
 * - 自动滚动到底部
 */

import { useState, useEffect, useRef } from "react";
import { MarkdownRenderer } from "./MarkdownRenderer";

interface Props {
  content: string;
  animate?: boolean;
  onAnimated?: () => void;
  onClose?: () => void;
}

export function MarkdownOverlay({ content, animate = false, onAnimated, onClose }: Props) {
  const [displayed, setDisplayed] = useState(animate ? "" : content);
  const indexRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 打字机动画效果
  useEffect(() => {
    if (!animate || !content) {
      setDisplayed(content);
      return;
    }

    indexRef.current = 0;
    setDisplayed("");

    timerRef.current = setInterval(() => {
      indexRef.current += 1;
      setDisplayed(content.slice(0, indexRef.current));

      if (indexRef.current >= content.length) {
        if (timerRef.current) clearInterval(timerRef.current);
        onAnimated?.();
      }
    }, 15); // 每 15ms 显示一个字符

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [content, animate, onAnimated]);

  return (
    <div className="markdown-overlay">
      <div className="markdown-overlay-header">
        <h3>分析报告</h3>
        {onClose && <button onClick={onClose} className="close-btn">✕</button>}
      </div>
      <div className="markdown-overlay-content">
        <MarkdownRenderer content={displayed} />
      </div>
    </div>
  );
}
