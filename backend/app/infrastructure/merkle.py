"""Merkle 树实现 — 事件链完整性验证

负责：
1. 构建事件链的 Merkle 树
2. 计算和验证 Merkle 根哈希
3. 使用 Ed25519 密钥对内容进行签名和验证
4. 提供 get_public_key_hex 供第三方审计

设计文档 § 2.6 — 完整性验证
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MerkleTree:
    """Merkle 树 — 用于事件链的完整性验证

    通过将事件哈希逐个追加到树中，构建可验证的事件链。
    支持增量追加和根哈希计算。
    """

    def __init__(self) -> None:
        """初始化空的 Merkle 树"""
        self._leaves: list[str] = []
        self._root_hash: str = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

    def append(self, event_hash: str) -> None:
        """追加一个事件哈希到 Merkle 树

        Args:
            event_hash: 事件的 SHA-256 哈希值
        """
        self._leaves.append(event_hash)
        self._recompute_root()

    def _recompute_root(self) -> None:
        """重新计算 Merkle 根哈希

        使用二叉树方式计算：将叶子节点两两配对哈希，
        直到只剩一个节点作为根。
        """
        if not self._leaves:
            self._root_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            return

        nodes = self._leaves[:]
        while len(nodes) > 1:
            next_level = []
            for i in range(0, len(nodes), 2):
                if i + 1 < len(nodes):
                    combined = nodes[i] + nodes[i + 1]
                else:
                    combined = nodes[i] + nodes[i]  # 奇数节点时复制自身
                h = hashlib.sha256(combined.encode("utf-8")).hexdigest()
                next_level.append(f"sha256:{h}")
            nodes = next_level
        self._root_hash = nodes[0]

    @property
    def root_hash(self) -> str:
        """当前 Merkle 树的根哈希"""
        return self._root_hash

    @property
    def leaf_count(self) -> int:
        """叶子节点数量"""
        return len(self._leaves)


def merkle_root(events: list[Any]) -> str:
    """计算事件列表的 Merkle 根哈希

    便捷函数：从事件列表构建 Merkle 树并返回根哈希。

    Args:
        events: 事件对象列表（需有 event_hash 属性）

    Returns:
        Merkle 根哈希字符串
    """
    tree = MerkleTree()
    for event in events:
        tree.append(event.event_hash)
    return tree.root_hash


# ---------------------------------------------------------------------------
# Ed25519 签名（用于第三方审计）
# ---------------------------------------------------------------------------

import os

_PRIVATE_KEY: bytes | None = None
_PUBLIC_KEY: bytes | None = None

try:
    from nacl.bindings import (
        crypto_sign_keypair,
        crypto_sign,
        crypto_sign_open,
    )
    _HAVE_NACL = True
except ImportError:
    _HAVE_NACL = False
    logger.info("PyNaCl not installed — Ed25519 signing disabled")


def _ensure_keys() -> None:
    """确保 Ed25519 密钥对已生成

    如果密钥对尚未生成，则生成新的密钥对。
    注意：生产环境应从安全存储加载密钥。
    """
    global _PRIVATE_KEY, _PUBLIC_KEY
    if _PRIVATE_KEY is None and _HAVE_NACL:
        _PRIVATE_KEY, _PUBLIC_KEY = crypto_sign_keypair()
        logger.info("Ed25519 key pair generated for content signing")


def sign_content(content: str) -> str:
    """使用 Ed25519 对内容进行签名

    Args:
        content: 要签名的内容字符串

    Returns:
        签名的十六进制字符串（前缀 "ed25519:"），
        如果 PyNaCl 不可用则返回 "ed25519:unavailable"
    """
    if not _HAVE_NACL:
        return "ed25519:unavailable"
    _ensure_keys()
    signed = crypto_sign(content.encode("utf-8"), _PRIVATE_KEY)
    return f"ed25519:{signed[:64].hex()}"


def verify_content(content: str, signature_hex: str, public_key_hex: str) -> bool:
    """验证 Ed25519 签名

    Args:
        content: 原始内容
        signature_hex: 签名的十六进制字符串
        public_key_hex: 公钥的十六进制字符串

    Returns:
        签名是否有效
    """
    if not _HAVE_NACL:
        return False
    try:
        pk = bytes.fromhex(public_key_hex)
        sig = bytes.fromhex(signature_hex)
        crypto_sign_open(sig + content.encode("utf-8"), pk)
        return True
    except Exception:
        return False


def get_public_key_hex() -> str:
    """获取 Ed25519 公钥的十六进制表示

    Returns:
        公钥的十六进制字符串，如果 PyNaCl 不可用则返回 "unavailable"
    """
    if not _HAVE_NACL:
        return "unavailable"
    _ensure_keys()
    return _PUBLIC_KEY.hex()
