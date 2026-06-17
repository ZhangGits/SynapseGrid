"""中央日志配置模块 — SynapseGrid MVP

配置根日志记录器输出到两个处理器：
  1. stdout — 被 ``docker logs`` / ``uvicorn`` 控制台捕获
  2. 轮转文件 — ``/tmp/synapsegrid/app.log``（持久化在 Docker 卷上，
     容器重建后仍然保留）

在 ``main.py`` 的 lifespan 启动时导入一次；每个模块通过
``logging.getLogger(__name__)`` 继承此配置。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

LOG_DIR = Path("/tmp/synapsegrid")
LOG_FILE = LOG_DIR / "app.log"

FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
)
DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(*, level: int = logging.INFO) -> None:
    """配置根日志记录器处理器，在应用启动时调用一次

    Args:
        level: 日志级别，默认为 INFO

    注意：如果根日志记录器已有处理器则跳过（防止热重载时重复附加）
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # 防止重复附加（例如热重载场景）
    if root.handlers:
        return

    # --- stdout 处理器（Docker / uvicorn）---
    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(level)
    stream.setFormatter(logging.Formatter(FORMAT, datefmt=DATE_FMT))
    root.addHandler(stream)

    # --- 轮转文件处理器（持久化在卷上）---
    file_handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(FORMAT, datefmt=DATE_FMT))
    root.addHandler(file_handler)

    # 保持嘈杂的第三方库日志安静
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # 输出可见的启动标记以确认日志工作正常
    logging.getLogger("synapsegrid").info(
        "╔══════════════════════════════════════════════════════════╗"
    )
    logging.getLogger("synapsegrid").info(
        "║  SynapseGrid MVP 3.1 — log configured                    ║"
    )
    logging.getLogger("synapsegrid").info(
        f"║  file: {LOG_FILE}  ║"
    )
    logging.getLogger("synapsegrid").info(
        "╚══════════════════════════════════════════════════════════╝"
    )
