"""Canvas UI component schemas — Pydantic v2 models for the 3 MVP components.

These models are the Python-side single source of truth for the JSON Schema
that SynthesisAgent outputs in canvas mode and that CanvasViewer renders.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Position (shared) ────────────────────────────────────────────

class Position(BaseModel):
    x: int = Field(ge=0, le=11, default=0)
    y: int = Field(ge=0, default=0)
    w: int = Field(ge=2, le=12, default=4)
    h: int = Field(ge=2, le=12, default=4)


# ── Component definitions ────────────────────────────────────────

class MarkdownComponent(BaseModel):
    id: str = Field(description="Unique component identifier")
    type: Literal["markdown"] = "markdown"
    semantic_tags: list[str] = Field(default_factory=lambda: ["insight"])
    priority_level: int = Field(default=3, ge=1, le=5)
    version: int = Field(default=1, ge=1)
    position: Position = Field(default_factory=Position)
    content: str = Field(default="", max_length=2000)


class BarChartVisualConfig(BaseModel):
    color: str = "#1890ff"
    show_legend: bool = True
    orientation: Literal["vertical", "horizontal"] = "vertical"
    stacked: bool = False


class BarChartComponent(BaseModel):
    id: str
    type: Literal["bar_chart"] = "bar_chart"
    semantic_tags: list[str] = Field(default_factory=lambda: ["primary", "comparison"])
    priority_level: int = Field(default=3, ge=1, le=5)
    version: int = Field(default=1, ge=1)
    position: Position = Field(default_factory=Position)
    visual_config: BarChartVisualConfig = Field(default_factory=BarChartVisualConfig)
    categories: list[str] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)


# ── Top-level schema ─────────────────────────────────────────────

# Union type for any component
CanvasComponent = MarkdownComponent | BarChartComponent


class CanvasSchema(BaseModel):
    """Top-level canvas schema — what SynthesisAgent outputs."""
    version: int = Field(default=1, ge=1)
    layout_type: Literal["grid", "report"] = "report"
    components: list[dict] = Field(default_factory=list)


# ── LLM output helpers ───────────────────────────────────────────

CANVAS_SYSTEM_PROMPT = (
    "You are a UI generation agent for SynapseGrid. Based on the Research "
    "findings, produce a polished, visually-rich canvas layout. "
    "Output ONLY a valid JSON object with this structure:\n"
    '{"version": 1, "layout_type": "report", "components": [...]}\n\n'
    "Available component types:\n"
    "1. markdown — Rich text block. Use for ALL narrative content.\n"
    "   Fields: id, type('markdown'), semantic_tags, priority_level(1-5), "
    "   version(1), position{x,y,w,h}, content(max 3000 chars).\n"
    "   semantic_tags: [hero_title], [section_heading], [body], [callout], "
    "   [metrics_summary], [conclusion].\n\n"
    "   For content: use proper Markdown with headings (##), bold, bullet "
    "   lists, and tables where appropriate. No YAML frontmatter.\n\n"
    "2. bar_chart — Polished SVG bar chart with gradients and labels.\n"
    "   Use only when comparing 3-6 categories side by side.\n"
    "   Fields: id, type('bar_chart'), semantic_tags([comparison],[trend]), "
    "   priority_level, version, position{x,y,w,h},\n"
    "   visual_config{color(hex), show_legend(bool), orientation(vertical|horizontal), "
    "   stacked(bool)}, categories(string[3-6]), values(number[3-6]).\n\n"
    "Layout rules — THESE ARE REQUIRED:\n"
    "- Component 1 (comp_001): markdown at x=0, y=0, w=12, h=3, "
    "  semantic_tags=[hero_title, summary]. Write a compelling H1 title "
    "  and a 2-3 sentence executive summary below it.\n"
    "- Component 2 (comp_002): markdown at x=0, y=3, w=12, h=5, "
    "  semantic_tags=[body, analysis]. Detailed analysis with ## headings, "
    "  bullet lists, bold for emphasis. Reference finding IDs where relevant.\n"
    "- Component 3 (comp_003): OPTIONAL bar_chart at x=0, y=8, w=12, h=5, "
    "  only when the data supports a meaningful visual comparison.\n"
    "- Component 4 (comp_004): markdown at x=0, y=13, w=12, h=3, "
    "  semantic_tags=[conclusion]. Concise recommendations in 1-2 paragraphs.\n"
    "- Each component needs a unique id (comp_001, comp_002...).\n"
    "- NEVER include kpi_card components.\n"
    "No text outside the JSON object."
)

FEEDBACK_SYSTEM_PROMPT = (
    "You are a UI feedback agent for SynapseGrid. The user has interacted with "
    "a canvas UI and provided feedback. Return a partial update to modify the "
    "UI components.\n\n"
    "Output ONLY a valid JSON object:\n"
    '{"action": "partial_update", "target_version": <int>, "updates": [...]}\n\n'
    "Each update has: id (component id), version (increment by 1). "
    "Include only the fields that CHANGED. Use null to delete a field.\n"
    "Supported update fields per component type:\n"
    "- markdown: position, content\n"
    "- kpi_card: position, visual_config{prefix,suffix,precision,color}\n"
    "- bar_chart: position, visual_config{color,show_legend,orientation,stacked}, categories, values\n"
    "Rules:\n"
    "- If the user drags a component, update position only.\n"
    "- If the user clicks a data point and asks for analysis, update a nearby markdown's content.\n"
    "- If the user asks to change style (color, orientation), update visual_config only.\n"
    "- target_version = current base_version + 1.\n"
    "- Never change a component's type.\n"
    "No text outside the JSON object."
)
