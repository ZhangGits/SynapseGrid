"""FastAPI 应用入口 — SynapseGrid MVP 后端主模块

负责：
1. 应用生命周期管理（通过 lifespan 上下文管理器）
2. CORS 中间件配置（从环境变量读取允许的来源）
3. HTTP 请求访问日志中间件
4. 路由注册（tasks 和 verify 两个路由器）
5. 健康检查端点（/health）和根端点（/）
6. 启动时 HMAC 密钥安全检查
"""

from contextlib import asynccontextmanager
import logging
import os
import shutil
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api.v1.tasks import router as tasks_router
from app.api.v1.verify import router as verify_router
from app.core.logging_config import setup_logging
from app.core.session_manager import session_manager

logger = logging.getLogger("synapsegrid.api")

# 内存速率限制器：基于客户端 IP，生产环境可换 Redis
class SimpleRateLimiter:
    """简单内存速率限制器（基于 IP + 滑动窗口）"""
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._records: dict[str, list[float]] = {}

    def is_allowed(self, ip: str) -> bool:
        import time
        now = time.time()
        window_start = now - self.window_seconds
        # 清理过期记录
        records = self._records.get(ip, [])
        records = [t for t in records if t > window_start]
        if len(records) >= self.max_requests:
            self._records[ip] = records
            return False
        records.append(now)
        self._records[ip] = records
        return True

rate_limiter = SimpleRateLimiter(max_requests=10, window_seconds=60)


def _check_hmac_key() -> None:
    """检查 HMAC 密钥是否已配置为安全值

    生产环境必须设置 SYNAPSEGRID_HMAC_KEY 环境变量，
    且密钥长度至少 32 字节。

    开发环境（使用默认密钥 dev-only-change-me-must-be-32-bytes）：
    - 仅打印警告，不阻止启动
    - 方便 docker compose up 开箱即用

    生产环境（非默认密钥）：
    - 密钥长度不足 32 字节时拒绝启动

    Raises:
        RuntimeError: 生产环境密钥未设置或长度不足时抛出
    """
    key = os.environ.get("SYNAPSEGRID_HMAC_KEY", "")
    if not key:
        msg = (
            "SYNAPSEGRID_HMAC_KEY is not set! "
            "Set a secure key (>=32 bytes) in environment variables."
        )
        logger.critical(msg)
        raise RuntimeError(msg)
    if key == "dev-only-change-me-must-be-32-bytes":
        logger.warning(
            "SYNAPSEGRID_HMAC_KEY is set to the default development key. "
            "This is INSECURE for production. Generate a new key for production use."
        )
        return  # 开发环境允许使用默认密钥
    if len(key.encode("utf-8")) < 32:
        msg = (
            "SYNAPSEGRID_HMAC_KEY is too short (%d bytes). "
            "It must be at least 32 bytes for security."
        ) % len(key.encode("utf-8"))
        logger.critical(msg)
        raise RuntimeError(msg)
    logger.info("HMAC key check passed (%d bytes)", len(key.encode("utf-8")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化日志、检查 HMAC 密钥、启动会话管理器，关闭时清理会话"""
    setup_logging()
    _check_hmac_key()
    logger.info("Session manager starting …")
    await session_manager.start()
    logger.info("Session manager started — ready for requests")
    yield
    logger.info("Shutting down …")
    await session_manager.stop()
    logger.info("Session manager stopped")


app = FastAPI(title="SynapseGrid MVP", version="3.1-mvp", lifespan=lifespan)

# HTTPS 强制中间件：生产环境时 HTTP 请求 308 到 HTTPS
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
if ENVIRONMENT == "production":
    @app.middleware("http")
    async def https_redirect(request: Request, call_next):
        """HTTPS 强制重定向中间件"""
        # 仅在非 HTTPS 请求时重定向（通过 X-Forwarded-Proto 判断）
        proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
        if proto == "http":
            from starlette.responses import RedirectResponse
            url = request.url.replace(scheme="https")
            return RedirectResponse(str(url), status_code=308)
        return await call_next(request)
    logger.info("HTTPS redirect middleware enabled (production mode)")
else:
    logger.info("Running in development mode — HTTPS redirect disabled")

# CORS 中间件：从环境变量获取允许的来源，生产环境必须配置
# 设置 SYNAPSEGRID_CORS_ORIGINS 环境变量，多个来源用逗号分隔
# 例如：SYNAPSEGRID_CORS_ORIGINS=https://app.example.com,https://admin.example.com
ALLOWED_ORIGINS_STR = os.environ.get(
    "SYNAPSEGRID_CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000",
)
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS_STR.split(",") if o.strip()]
logger.info("CORS allowed origins: %s", ALLOWED_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 请求级访问日志（每请求一行，格式与日志文件一致）
# ---------------------------------------------------------------------------
@app.middleware("http")
async def access_log(request: Request, call_next):
    """HTTP 请求访问日志中间件：记录方法、路径、状态码和耗时"""
    from time import perf_counter

    start = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - start) * 1000
    logger.info(
        "%s %s → %s (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# 请求体大小和 prompt 长度限制中间件
# ---------------------------------------------------------------------------
@app.middleware("http")
async def request_size_limit(request: Request, call_next):
    """请求体大小限制中间件：限制 prompt 长度不超过 8000 字符"""
    if request.method == "POST" and request.url.path == "/api/v1/tasks":
        body = await request.body()
        try:
            import json
            data = json.loads(body)
            prompt = data.get("prompt", "")
            if len(prompt) > 8000:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Prompt too long: {len(prompt)} chars (max 8000)"},
                )
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        # 重新构造请求，因为 body 已被消费
        async def receive():
            return {"type": "http.request", "body": body}
        request = Request(request.scope, receive, request._send)
    return await call_next(request)


# ---------------------------------------------------------------------------
# 速率限制中间件
# ---------------------------------------------------------------------------
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """速率限制中间件：POST /api/v1/tasks 每 IP 每分钟最多 10 次"""
    if request.method == "POST" and request.url.path == "/api/v1/tasks":
        client_ip = request.client.host if request.client else "unknown"
        if not rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Max 10 requests per minute."},
            )
    return await call_next(request)


# 注册路由：所有 API 端点挂载在 /api/v1 前缀下
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(verify_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, object]:
    """根端点：返回应用基本信息、前端地址和可用端点列表"""
    return {
        "name": "SynapseGrid MVP",
        "status": "running",
        "frontend": "http://localhost:5173",
        "endpoints": {
            "health": "/health",
            "verifys": ["create_task", "rollback", "verify", "close"],
            "docs": "/docs",
        },
    }


@app.get("/health")
async def health() -> dict[str, object]:
    """健康检查端点：验证 SQLite 存储可写、检查磁盘水位，返回可用模板列表"""
    import sqlite3, tempfile

    # 1. SQLite 存储检查
    storage_ok = True
    try:
        tmp_dir = tempfile.gettempdir()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False, dir=tmp_dir) as p:
            tmp_path = p.name
        try:
            conn = sqlite3.connect(tmp_path)
            conn.execute("CREATE TABLE hc (v INTEGER)")
            conn.execute("INSERT INTO hc VALUES (1)")
            row = conn.execute("SELECT v FROM hc").fetchone()
            conn.close()
            if row is None or row[0] != 1:
                storage_ok = False
        finally:
            os.unlink(tmp_path)
    except Exception:
        storage_ok = False

    # 2. 磁盘水位检查（会话存储目录）
    disk_ok = True
    disk_usage = None
    try:
        sessions_dir = "/tmp/synapse_sessions"
        os.makedirs(sessions_dir, exist_ok=True)
        total, used, free = shutil.disk_usage(sessions_dir)
        disk_usage = {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "usage_percent": round(used / total * 100, 1),
        }
        # 磁盘使用率超过 90% 视为不健康
        if disk_usage["usage_percent"] > 90:
            disk_ok = False
    except Exception:
        disk_ok = False

    # 3. 活动会话统计
    active_sessions = len(session_manager.active_sessions)

    from app.services.template_engine import available_templates
    overall_status = "ok" if (storage_ok and disk_ok) else "degraded"

    return {
        "status": overall_status,
        "storage": "writable" if storage_ok else "error",
        "disk": disk_ok,
        "disk_usage": disk_usage,
        "active_sessions": active_sessions,
        "templates": available_templates(),
        "version": "3.1-mvp",
    }
