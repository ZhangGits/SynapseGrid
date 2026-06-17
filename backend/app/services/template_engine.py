"""模板引擎 — 管理场景模板的加载和渲染

负责：
1. 从 templates 目录加载场景模板文件
2. 根据模板名称返回可用模板列表
3. 渲染模板（将用户 prompt 填充到模板中）

模板文件为 YAML 格式，包含 system_prompt 和 analysis_dimensions。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def available_templates() -> list[str]:
    """返回所有可用模板的名称列表

    扫描 templates 目录下的 .yaml 文件，返回文件名（不含扩展名）。

    Returns:
        模板名称列表，如 ["general", "finance", "legal"]
    """
    if not TEMPLATES_DIR.exists():
        logger.warning("Templates directory not found: %s", TEMPLATES_DIR)
        return ["general"]
    templates = []
    for f in sorted(TEMPLATES_DIR.glob("*.yaml")):
        templates.append(f.stem)
    if not templates:
        templates = ["general"]
    return templates


def load_template(name: str) -> dict | None:
    """加载指定名称的模板

    Args:
        name: 模板名称（不含扩展名）

    Returns:
        模板字典，包含 system_prompt 和 analysis_dimensions 等字段；
        如果模板不存在则返回 None
    """
    path = TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        logger.warning("Template not found: %s", path)
        return None
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def render_template(name: str, prompt: str) -> str | None:
    """渲染模板：将用户 prompt 填充到模板中

    Args:
        name: 模板名称
        prompt: 用户输入

    Returns:
        渲染后的完整 prompt 字符串；如果模板不存在则返回 None
    """
    template = load_template(name)
    if template is None:
        return None
    system_prompt = template.get("system_prompt", "")
    dimensions = template.get("analysis_dimensions", [])
    dimensions_text = "\n".join(f"- {d}" for d in dimensions)
    return f"{system_prompt}\n\n分析维度：\n{dimensions_text}\n\n用户问题：\n{prompt}"
