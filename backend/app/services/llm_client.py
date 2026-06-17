"""LLM 客户端 — 统一的 LLM API 调用封装

负责：
1. 支持 OpenAI 兼容接口（OpenAI、DeepSeek、Qwen、Moonshot 等）
2. 支持 Anthropic Claude 接口
3. 统一的调用接口，自动选择正确的 API 格式
4. Token 计数和成本追踪
5. LLMEngine 黑盒封装 — 上层无需关心 provider/model 选择

支持的提供商：
- chatgpt: OpenAI 兼容接口
- deepseek: DeepSeek API
- claude: Anthropic Claude API
- qwen: 通义千问 API
- kimi: Moonshot API
- gemini: Google Gemini API
- custom: 自定义 OpenAI 兼容接口
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.schemas.machine_wire import LlmConfig
from app.services.cost_tracker import MODEL_PRICING
from app.services.token_counter import count_tokens

logger = logging.getLogger(__name__)

# 默认 API 基础地址
DEFAULT_BASE_URLS: dict[str, str] = {
    "chatgpt": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}

# 需要特殊处理的提供商（非 OpenAI 兼容格式）
SPECIAL_PROVIDERS = {"claude", "gemini"}

# 模型 → 默认 provider 映射（自动修正不匹配的 provider）
MODEL_PROVIDER_MAP: dict[str, str] = {
    # OpenAI 模型
    "gpt-4o": "chatgpt",
    "gpt-4o-mini": "chatgpt",
    "gpt-4-turbo": "chatgpt",
    "gpt-4": "chatgpt",
    "gpt-3.5-turbo": "chatgpt",
    # DeepSeek 模型
    "deepseek-chat": "deepseek",
    "deepseek-reasoner": "deepseek",
    # Claude 模型
    "claude-3-5-sonnet": "claude",
    "claude-3-5-haiku": "claude",
    "claude-3-opus": "claude",
    "claude-3-haiku": "claude",
    # Qwen 模型
    "qwen-turbo": "qwen",
    "qwen-plus": "qwen",
    "qwen-max": "qwen",
    # Moonshot 模型
    "moonshot-v1-8k": "kimi",
    "moonshot-v1-32k": "kimi",
    "moonshot-v1-128k": "kimi",
    # Gemini 模型
    "gemini-1.5-pro": "gemini",
    "gemini-1.5-flash": "gemini",
}


def _get_api_base(llm: LlmConfig) -> str:
    """获取 API 基础地址

    Args:
        llm: LLM 配置

    Returns:
        API 基础地址字符串
    """
    if llm.base_url:
        return llm.base_url.rstrip("/")
    return DEFAULT_BASE_URLS.get(llm.provider, "https://api.openai.com/v1")


async def _call_openai_compatible(
    llm: LlmConfig,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """调用 OpenAI 兼容接口

    支持 OpenAI、DeepSeek、Qwen、Moonshot 等提供商。

    Args:
        llm: LLM 配置
        messages: 消息列表
        temperature: 温度参数
        max_tokens: 最大输出 Token 数

    Returns:
        LLM 响应字典，包含 content、tokens_input、tokens_output 等字段

    Raises:
        httpx.HTTPError: API 调用失败时抛出
    """
    base_url = _get_api_base(llm)
    url = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {llm.api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": llm.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    choice = data["choices"][0]
    content = choice["message"]["content"]

    # 提取 Token 使用情况
    usage = data.get("usage", {})
    tokens_input = usage.get("prompt_tokens", count_tokens(
        json.dumps(messages, ensure_ascii=False), llm.model,
    ))
    tokens_output = usage.get("completion_tokens", count_tokens(content, llm.model))

    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "finish_reason": choice.get("finish_reason", ""),
        "model": data.get("model", llm.model),
    }


async def _call_claude(
    llm: LlmConfig,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """调用 Anthropic Claude API

    Args:
        llm: LLM 配置
        messages: 消息列表
        temperature: 温度参数
        max_tokens: 最大输出 Token 数

    Returns:
        LLM 响应字典

    Raises:
        httpx.HTTPError: API 调用失败时抛出
    """
    base_url = _get_api_base(llm)
    url = f"{base_url}/messages"

    headers = {
        "x-api-key": llm.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    # 将 system 消息分离出来
    system_msg = None
    claude_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg = msg["content"]
        else:
            claude_messages.append({"role": msg["role"], "content": msg["content"]})

    payload: dict[str, Any] = {
        "model": llm.model,
        "messages": claude_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_msg:
        payload["system"] = system_msg

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = data["content"][0]["text"]

    # Claude API 的 Token 使用情况
    usage = data.get("usage", {})
    tokens_input = usage.get("input_tokens", count_tokens(
        json.dumps(messages, ensure_ascii=False), llm.model,
    ))
    tokens_output = usage.get("output_tokens", count_tokens(content, llm.model))

    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "finish_reason": data.get("stop_reason", ""),
        "model": data.get("model", llm.model),
    }


async def _call_gemini(
    llm: LlmConfig,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """调用 Google Gemini API

    Gemini 使用 OpenAI 兼容接口（通过 base_url 区分），
    但认证方式不同（使用 API key 作为 query 参数）。

    Args:
        llm: LLM 配置
        messages: 消息列表
        temperature: 温度参数
        max_tokens: 最大输出 Token 数

    Returns:
        LLM 响应字典

    Raises:
        httpx.HTTPError: API 调用失败时抛出
    """
    base_url = _get_api_base(llm)
    # Gemini OpenAI 兼容端点
    url = f"{base_url}/openai/chat/completions"

    headers = {
        "Authorization": f"Bearer {llm.api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": llm.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    choice = data["choices"][0]
    content = choice["message"]["content"]

    usage = data.get("usage", {})
    tokens_input = usage.get("prompt_tokens", count_tokens(
        json.dumps(messages, ensure_ascii=False), llm.model,
    ))
    tokens_output = usage.get("completion_tokens", count_tokens(content, llm.model))

    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "finish_reason": choice.get("finish_reason", ""),
        "model": data.get("model", llm.model),
    }


# ------------------------------------------------------------------
# 路由注册表 — 按 API 格式分类（不是按 provider）
# ------------------------------------------------------------------
# OpenAI 兼容格式：chatgpt, deepseek, qwen, kimi, custom
# Claude 原生格式：claude
# Gemini 原生格式：gemini
OPENAI_COMPATIBLE = {"chatgpt", "deepseek", "qwen", "kimi", "custom"}


async def call_llm(
    llm: LlmConfig,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """统一的 LLM API 调用入口 — 路由层

    根据 provider 自动路由到正确的 API 格式调用器：
    - OpenAI 兼容格式 → _call_openai_compatible()
    - Claude 原生格式 → _call_claude()
    - Gemini 原生格式 → _call_gemini()

    上层模块（Agent、Orchestrator）只需调用此方法，完全无感知底层差异。

    Args:
        llm: LLM 配置（provider、model、api_key、base_url）
        messages: 消息列表
        temperature: 温度参数
        max_tokens: 最大输出 Token 数

    Returns:
        标准化响应字典（content, tokens_input, tokens_output, finish_reason, model）

    Raises:
        httpx.HTTPError: API 调用失败时抛出
    """
    logger.debug(
        "LLM call  provider=%s  model=%s  messages=%s",
        llm.provider, llm.model, len(messages),
    )

    # 路由决策：按 API 格式分类
    if llm.provider in OPENAI_COMPATIBLE:
        return await _call_openai_compatible(llm, messages, temperature, max_tokens)
    elif llm.provider == "claude":
        return await _call_claude(llm, messages, temperature, max_tokens)
    elif llm.provider == "gemini":
        return await _call_gemini(llm, messages, temperature, max_tokens)
    else:
        # 未知 provider 默认尝试 OpenAI 兼容格式
        logger.warning(
            "Unknown provider '%s', defaulting to OpenAI compatible format",
            llm.provider,
        )
        return await _call_openai_compatible(llm, messages, temperature, max_tokens)


def estimate_cost(
    model: str,
    tokens_input: int,
    tokens_output: int,
) -> float:
    """估算 LLM 调用的费用

    Args:
        model: 模型名称
        tokens_input: 输入 Token 数
        tokens_output: 输出 Token 数

    Returns:
        估算费用（美元）
    """
    pricing = MODEL_PRICING.get(model, {"input": 0.001, "output": 0.002})
    return (
        tokens_input * pricing["input"] / 1000
        + tokens_output * pricing["output"] / 1000
    )


def _resolve_provider(model: str) -> str:
    """根据模型名称自动推断 provider

    Args:
        model: 模型名称

    Returns:
        provider 名称
    """
    # 精确匹配
    if model in MODEL_PROVIDER_MAP:
        return MODEL_PROVIDER_MAP[model]
    # 前缀匹配（如 gpt-4o-2024-08-06 匹配到 gpt-4o）
    for known_model, provider in MODEL_PROVIDER_MAP.items():
        if model.startswith(known_model):
            return provider
    # 兜底：尝试从模型名推断
    if model.startswith(("gpt-", "o1", "o3")):
        return "chatgpt"
    if model.startswith("deepseek"):
        return "deepseek"
    if model.startswith("claude"):
        return "claude"
    if model.startswith("qwen"):
        return "qwen"
    if model.startswith("moonshot"):
        return "kimi"
    if model.startswith("gemini"):
        return "gemini"
    logger.warning("Cannot resolve provider for model %s, defaulting to chatgpt", model)
    return "chatgpt"


class LLMEngine:
    """LLM 引擎 — 黑盒封装层

    上层模块（Agent、Orchestrator）无需关心：
    - provider 选择
    - API 格式差异（OpenAI/Claude/Gemini）
    - 模型名称到 provider 的映射

    只需传入 api_key 和 model，引擎自动处理一切。
    """

    @staticmethod
    def build_config(api_key: str, model: str, base_url: str | None = None) -> LlmConfig:
        """构建标准化的 LLM 配置

        根据 model 自动推断 provider，上层无需手动设置 provider。

        Args:
            api_key: API 密钥
            model: 模型名称（如 "gpt-4o-mini", "deepseek-chat", "claude-3-haiku"）
            base_url: 自定义 API 地址（可选）

        Returns:
            标准化的 LlmConfig
        """
        provider = _resolve_provider(model)
        return LlmConfig(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )

    @staticmethod
    async def chat(
        config: LlmConfig,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        messages: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """统一的聊天接口 — 上层唯一需要调用的方法

        支持两种调用方式：
        1. 传入 system_prompt + user_prompt（简单场景）
        2. 传入 messages（完整对话场景）

        Args:
            config: LLM 配置（由 build_config 生成）
            system_prompt: 系统提示词（可选）
            user_prompt: 用户提示词（可选）
            messages: 完整消息列表（可选，与 prompt 二选一）
            temperature: 温度参数
            max_tokens: 最大输出 Token 数

        Returns:
            LLM 响应字典（content, tokens_input, tokens_output, finish_reason, model）
        """
        # 构建 messages
        if messages is not None:
            msgs = messages
        else:
            msgs = []
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            if user_prompt:
                msgs.append({"role": "user", "content": user_prompt})

        if not msgs:
            raise ValueError("Either messages or at least one prompt must be provided")

        # 自动修正 provider（防御性编程）
        if config.provider not in DEFAULT_BASE_URLS and config.provider != "custom":
            resolved = _resolve_provider(config.model)
            if resolved != config.provider:
                logger.warning(
                    "Provider mismatch detected: config says %s but model %s resolves to %s. "
                    "Auto-correcting.",
                    config.provider, config.model, resolved,
                )
                config = LlmConfig(
                    provider=resolved,
                    model=config.model,
                    api_key=config.api_key,
                    base_url=config.base_url,
                )

        return await call_llm(config, msgs, temperature, max_tokens)

    @staticmethod
    def estimate_call_cost(config: LlmConfig, tokens_input: int, tokens_output: int) -> float:
        """估算调用成本

        Args:
            config: LLM 配置
            tokens_input: 输入 Token 数
            tokens_output: 输出 Token 数

        Returns:
            估算费用（美元）
        """
        return estimate_cost(config.model, tokens_input, tokens_output)
