"""后处理器单元测试

测试 with_audit_header 和 _sign_content 函数。
"""

from __future__ import annotations

from app.services.post_processor import with_audit_header


class TestPostProcessor:
    """后处理器测试类"""

    def test_audit_header_added(self):
        """测试审计头添加：验证返回内容包含审计头"""
        content, sig = with_audit_header(
            "# Hello",
            "sess_test",
            "sha256:abc",
            5,
        )
        assert content.startswith("---")
        assert "# synapsegrid_audit" in content
        assert "session_id: sess_test" in content
        assert "merkle_root: sha256:abc" in content
        assert "event_count: 5" in content
        assert "content_signature: hmac:" in content
        assert "# Hello" in content

    def test_signature_format(self):
        """测试签名格式：验证返回 hmac: 前缀"""
        content, sig = with_audit_header(
            "test content",
            "sess_1",
            "sha256:root",
            3,
        )
        assert sig.startswith("hmac:")
        assert len(sig) > 10

    def test_deterministic(self):
        """测试确定性：相同输入应产生相同签名"""
        _, sig1 = with_audit_header("hello", "s1", "r1", 1)
        _, sig2 = with_audit_header("hello", "s1", "r1", 1)
        assert sig1 == sig2
