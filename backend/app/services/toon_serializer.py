"""TOON 序列化器 — 结构化 Agent 通信格式

TOON (Tabular Object Notation) 格式：
- 基于 CSV 思想，去除 JSON 的引号、缩进、字段名重复
- 比 JSON 节省约 25-40% Token
- 人类可读，易于调试

格式示例：
findings[3]{id,claim,confidence}:
  f1,"NEV sales +45.2% YoY",0.92
  f2,"CATL battery cost $80/kWh",0.85

支持的格式：
- toon: TOON 格式（最紧凑）
- json: JSON 格式（人类可读降级）
- diff: Diff 格式（增量更新）
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TOONSerializer:
    """TOON 序列化器

    将 finding 列表、验证结果等数据结构序列化为 TOON 格式，
    比 JSON 节省约 25-40% Token。
    """

    @staticmethod
    def findings_to_toon(findings: list[dict[str, Any]], fields: list[str] | None = None) -> str:
        """将 finding 列表序列化为 TOON 格式

        Args:
            findings: finding 字典列表
            fields: 要包含的字段列表，默认 ["id", "claim", "confidence", "evidence", "source"]

        Returns:
            TOON 格式字符串
        """
        if not findings:
            return "findings[0]{}:"

        if fields is None:
            fields = ["id", "claim", "confidence", "evidence", "source"]

        # 收集所有实际存在的字段
        available_fields = [f for f in fields if any(f in finding for finding in findings)]

        header = f"findings[{len(findings)}]{{{','.join(available_fields)}}}:"
        lines = [header]

        for finding in findings:
            values = []
            for f in available_fields:
                v = finding.get(f, "")
                if isinstance(v, str):
                    # 如果字符串包含逗号或引号，需要引号包裹
                    if "," in v or '"' in v or "\n" in v:
                        v = '"' + v.replace('"', '""') + '"'
                    values.append(v)
                elif isinstance(v, (int, float)):
                    values.append(str(v))
                elif isinstance(v, bool):
                    values.append("1" if v else "0")
                else:
                    values.append(str(v) if v is not None else "")
            lines.append("  " + ",".join(values))

        return "\n".join(lines)

    @staticmethod
    def toon_to_findings(data: str) -> list[dict[str, Any]]:
        """从 TOON 格式反序列化为 finding 列表

        Args:
            data: TOON 格式字符串

        Returns:
            finding 字典列表
        """
        lines = [l.rstrip() for l in data.strip().split("\n")]
        lines = [l for l in lines if l.strip()]
        if not lines:
            return []

        # 解析头部：findings[N]{field1,field2}:
        header = lines[0]
        if "{" not in header or "}" not in header:
            raise ValueError(f"Invalid TOON header: {header}")

        fields_str = header[header.index("{") + 1:header.index("}")]
        fields = [f.strip() for f in fields_str.split(",") if f.strip()]

        findings = []
        for line in lines[1:]:
            if not line.startswith("  "):
                continue  # 跳过非数据行
            line = line[2:]  # 去除前导空格

            # 解析 CSV 格式
            reader = csv.reader(io.StringIO(line))
            row = next(reader, None)
            if not row:
                continue

            finding = {}
            for i, field in enumerate(fields):
                if i < len(row):
                    val = row[i].strip()
                    # 尝试类型转换
                    if field == "confidence":
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                    elif field in ("validated", "rolled_back"):
                        val = val == "1" or val.lower() == "true"
                    finding[field] = val
            findings.append(finding)

        return findings

    @staticmethod
    def validation_result_to_toon(validated_ids: list[str], conflicts: list[dict[str, Any]]) -> str:
        """将验证结果序列化为 TOON 格式

        Args:
            validated_ids: 通过验证的 finding ID 列表
            conflicts: 矛盾列表

        Returns:
            TOON 格式字符串
        """
        lines = [
            f"validated[{len(validated_ids)}]:",
        ]
        for vid in validated_ids:
            lines.append(f"  {vid}")

        lines.append(f"conflicts[{len(conflicts)}]{{id,between,severity,reason}}:")
        for c in conflicts:
            between = "|".join(c.get("between", []))
            reason = c.get("reason", c.get("type", ""))
            if "," in reason or '"' in reason:
                reason = '"' + reason.replace('"', '""') + '"'
            lines.append(f"  {c.get('id','')},{between},{c.get('severity','')},{reason}")

        return "\n".join(lines)

    @staticmethod
    def toon_to_validation_result(data: str) -> tuple[list[str], list[dict[str, Any]]]:
        """从 TOON 格式反序列化为验证结果

        Args:
            data: TOON 格式字符串

        Returns:
            (validated_ids, conflicts)
        """
        validated_ids: list[str] = []
        conflicts: list[dict[str, Any]] = []

        lines = [l.strip() for l in data.strip().split("\n") if l.strip()]
        section = None

        for line in lines:
            if line.startswith("validated["):
                section = "validated"
                continue
            elif line.startswith("conflicts["):
                section = "conflicts"
                continue

            if section == "validated" and line.startswith("  "):
                validated_ids.append(line.strip())
            elif section == "conflicts" and line.startswith("  "):
                parts = [p.strip() for p in line[2:].split(",")]
                if len(parts) >= 3:
                    conflicts.append({
                        "id": parts[0],
                        "between": parts[1].split("|") if "|" in parts[1] else [parts[1]],
                        "severity": parts[2],
                        "reason": parts[3] if len(parts) > 3 else "",
                    })

        return validated_ids, conflicts

    @staticmethod
    def compare_size(findings: list[dict[str, Any]]) -> dict[str, int]:
        """比较 TOON 和 JSON 格式的字符数

        Args:
            findings: finding 列表

        Returns:
            各格式的字符数统计
        """
        toon_data = TOONSerializer.findings_to_toon(findings)
        json_data = json.dumps(findings, ensure_ascii=False)

        return {
            "toon_chars": len(toon_data),
            "json_chars": len(json_data),
            "savings": len(json_data) - len(toon_data),
            "savings_percent": round((len(json_data) - len(toon_data)) / len(json_data) * 100, 1) if json_data else 0,
        }