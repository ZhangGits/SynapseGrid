"""Token 计数器 — 估算文本的 Token 数量

负责：
1. 使用 tiktoken 库（如果可用）精确计算 Token 数
2. 回退到基于字符的粗略估算
3. 提供统一的 count_tokens 接口

注意：tiktoken 是可选依赖，如果未安装则使用字符估算。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import tiktoken
    _HAVE_TIKTOKEN = True
except ImportError:
    _HAVE_TIKTOKEN = False
    logger.info("tiktoken not installed — using character-based token estimation")


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """估算文本的 Token 数量

    优先使用 tiktoken 精确计算，回退到字符估算（约 4 字符/Token）。

    Args:
        text: 要估算的文本
        model: 模型名称，用于选择正确的编码器

    Returns:
        估算的 Token 数量
    """
    if _HAVE_TIKTOKEN:
        try:
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except Exception:
            logger.debug("tiktoken failed for model %s, falling back", model)
    # 回退：中英文混合文本约 2-4 字符/Token
    return max(1, len(text) // 3)
