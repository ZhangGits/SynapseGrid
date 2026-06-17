"""HTTPS 重定向中间件测试"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


def test_https_redirect_in_production():
    """生产环境时 HTTP 请求应 308 到 HTTPS"""
    with patch.dict("os.environ", {"ENVIRONMENT": "production", "SYNAPSEGRID_HMAC_KEY": "dev-only-change-me-must-be-32-bytes"}):
        from app.main import app
        client = TestClient(app)
        # 模拟 HTTP 请求（带 X-Forwarded-Proto 头）
        response = client.get("/", headers={"X-Forwarded-Proto": "http"}, follow_redirects=False)
        assert response.status_code == 308
        assert response.headers["location"].startswith("https://")


def test_no_redirect_in_development():
    """开发环境时不应重定向"""
    with patch.dict("os.environ", {"ENVIRONMENT": "development", "SYNAPSEGRID_HMAC_KEY": "dev-only-change-me-must-be-32-bytes"}):
        from app.main import app
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200