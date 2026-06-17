/**
 * API 客户端 — 封装与后端的所有 HTTP 通信
 *
 * 提供以下函数：
 * - createTask: 创建新分析任务
 * - sendFeedback: 发送画布反馈
 * - rollbackFinding: 回退分析要点
 * - getVersions: 获取报告版本列表
 * - verifySession: 验证会话完整性
 *
 * API 基础路径从 Vite 环境变量 VITE_API_BASE 获取，
 * 默认值为 http://localhost:8000/api/v1。
 */

import type { IntentPayload, LlmConfig, PerAgentLlm, TaskResponse, VersionInfo } from "../types";

/** 从 Vite 环境变量获取 API 基础路径 */
const API_BASE = (import.meta as any).env?.VITE_API_BASE ?? "http://localhost:8000/api/v1";

/** 创建新分析任务（异步模式，立即返回 session_id） */
export async function createTask(
  prompt: string,
  llm: LlmConfig,
  perAgent: PerAgentLlm,
  template: string,
  outputMode: string,
  conversationHistory?: string,
): Promise<{ session_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: "user001", prompt, llm, template,
      output_mode: outputMode,
      llm_research: perAgent.research,
      llm_verification: perAgent.verification,
      llm_synthesis: perAgent.synthesis,
      conversation_history: conversationHistory || undefined,
    }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

/** 获取任务执行进度 */
export async function getTaskProgress(sessionId: string): Promise<{
  session_id: string;
  completed_stages: string[];
  event_count: number;
  has_result: boolean;
}> {
  const response = await fetch(`${API_BASE}/tasks/${sessionId}/progress`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

/** 获取任务结果 */
export async function getTaskResult(sessionId: string): Promise<TaskResponse | null> {
  const response = await fetch(`${API_BASE}/tasks/${sessionId}/result`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

/** 发送画布反馈 */
export async function sendFeedback(
  sessionId: string,
  intent: IntentPayload,
): Promise<TaskResponse> {
  const response = await fetch(`${API_BASE}/tasks/${sessionId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(intent),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

/** 回退分析要点 */
export async function rollbackFinding(sessionId: string, findingId: string): Promise<TaskResponse> {
  const response = await fetch(`${API_BASE}/tasks/${sessionId}/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ finding_id: findingId, reason: "Rolled back from analyst UI" }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

/** 获取报告版本列表 */
export async function getVersions(sessionId: string): Promise<{ session_id: string; versions: VersionInfo[] }> {
  const response = await fetch(`${API_BASE}/tasks/${sessionId}/versions`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

/** 简化验证会话完整性 — 只需 session_id */
export async function verifySessionSimple(sessionId: string): Promise<{
  valid: boolean;
  session_id: string;
  merkle_root: string;
  event_count: number;
  content_signature: string;
  message: string;
}> {
  const response = await fetch(`${API_BASE}/verify/simple`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

/** 获取会话完整事件流 */
export async function getEvents(sessionId: string): Promise<{
  session_id: string;
  event_count: number;
  merkle_root: string;
  events: {
    version: number;
    event_type: string;
    payload: any;
    metadata: any;
    event_hash: string;
    created_at: string;
  }[];
}> {
  const response = await fetch(`${API_BASE}/tasks/${sessionId}/events`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
