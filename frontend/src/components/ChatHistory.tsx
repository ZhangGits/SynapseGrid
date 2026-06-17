/**
 * 聊天历史组件 — 显示消息列表
 *
 * 展示用户和机器人的对话历史。
 * 每条消息支持查看报告和查看审计操作。
 * 空状态时显示示例 prompt 卡片。
 */

import type { ChatMessage } from "../types";
import { AgentAnalysisNodes } from "./AgentAnalysisNodes";

interface Props {
  messages: ChatMessage[];
  onViewReport: (msg: ChatMessage) => void;
  onViewAudit: (msg: ChatMessage) => void;
  onUseExample: (text: string) => void;
  /** 当前是否有任务在分析中 */
  loading?: boolean;
  /** 当前输出模式：markdown 或 canvas */
  outputMode?: string;
}

const EXAMPLES = [
  "分析人工智能在医疗领域的最新发展趋势",
  "评估新能源汽车行业的投资机会",
  "分析中美贸易摩擦对全球供应链的影响",
];

export function ChatHistory({ messages, onViewReport, onViewAudit, onUseExample, loading = false, outputMode = "markdown" }: Props) {
  if (messages.length === 0) {
    return (
      <div className="chat-history empty">
        <div className="empty-state">
          <h2>开始分析</h2>
          <p>选择一个示例或输入自定义问题</p>
          <div className="example-cards">
            {EXAMPLES.map((text, i) => (
              <button
                key={i}
                className="example-card"
                onClick={() => onUseExample(text)}
              >
                {text}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // 检查是否有正在分析中的消息（最后一条没有 response）
  const lastMsg = messages[messages.length - 1];
  const hasPending = loading && lastMsg && !lastMsg.response;

  return (
    <div className="chat-history">
      {messages.map((msg) => (
        <div key={msg.id} className={`message ${msg.response ? "bot" : "user"}`}>
          <div className="message-header">
            <span className="message-role">
              {msg.response ? "🤖 Agent" : "👤 用户"}
            </span>
          </div>
          <div className="message-content">
            <p>{msg.prompt}</p>
          </div>
          {msg.response && (
            <div className="message-actions">
              <button onClick={() => onViewReport(msg)}>查看报告</button>
              <button onClick={() => onViewAudit(msg)}>审计</button>
            </div>
          )}
        </div>
      ))}
          {/* 分析中状态：显示多轮 Agent 分析节点 */}
      {hasPending && (
        <div className="message bot agent-analysis-message">
          <div className="message-header">
            <span className="message-role">🤖 Agent</span>
          </div>
          <AgentAnalysisNodes
            outputMode={outputMode}
            loading={loading}
            completedStages={lastMsg?.completed_stages || []}
          />
        </div>
      )}
    </div>
  );
}
