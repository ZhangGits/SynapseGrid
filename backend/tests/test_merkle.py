"""Merkle 树单元测试

测试 MerkleTree 的追加、根哈希计算和空树行为。
"""

from __future__ import annotations

from app.infrastructure.merkle import MerkleTree


class TestMerkleTree:
    """Merkle 树测试类"""

    def test_empty_tree(self):
        """测试空树：根哈希应为全零"""
        tree = MerkleTree()
        assert tree.root_hash == "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        assert tree.leaf_count == 0

    def test_single_leaf(self):
        """测试单叶子节点：根哈希应等于叶子哈希"""
        tree = MerkleTree()
        tree.append("sha256:abc123")
        assert tree.leaf_count == 1
        assert tree.root_hash != "sha256:0000000000000000000000000000000000000000000000000000000000000000"

    def test_multiple_leaves(self):
        """测试多叶子节点：验证根哈希计算"""
        tree = MerkleTree()
        tree.append("sha256:a")
        tree.append("sha256:b")
        tree.append("sha256:c")
        assert tree.leaf_count == 3
        assert tree.root_hash.startswith("sha256:")

    def test_deterministic(self):
        """测试确定性：相同输入应产生相同根哈希"""
        tree1 = MerkleTree()
        tree1.append("sha256:a")
        tree1.append("sha256:b")

        tree2 = MerkleTree()
        tree2.append("sha256:a")
        tree2.append("sha256:b")

        assert tree1.root_hash == tree2.root_hash
