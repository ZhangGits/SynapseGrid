"""Diff 引擎 — Finding 列表增量更新

用于 Research → Verification 的增量传输：
- 只传递变化的 finding（added/modified/removed）
- unchanged 的 finding 只传 ID，大幅减少 Token

Diff 格式（TOON）：
diff{
  added[N]: <finding TOON 行>
  modified[N]: <finding TOON 行>
  unchanged[N]: <ID 列表>
  removed[N]: <ID 列表>
}
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.toon_serializer import TOONSerializer

logger = logging.getLogger(__name__)


class FindingDiffEngine:
    """Finding 列表 Diff 引擎

    比较两个 finding 列表，生成增量更新。
    """

    @staticmethod
    def compute_diff(
        old_findings: list[dict[str, Any]],
        new_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """计算两个 finding 列表的差异

        Args:
            old_findings: 旧的 finding 列表
            new_findings: 新的 finding 列表

        Returns:
            Diff 结果字典，包含 added/modified/unchanged/removed
        """
        old_map = {f.get("id", f.get("finding_id", "")): f for f in old_findings}
        new_map = {f.get("id", f.get("finding_id", "")): f for f in new_findings}

        added: list[dict[str, Any]] = []
        modified: list[dict[str, Any]] = []
        unchanged: list[str] = []
        removed: list[str] = []

        # 检查新列表中的 finding
        for fid, new_f in new_map.items():
            if fid not in old_map:
                added.append(new_f)
            elif FindingDiffEngine._is_different(old_map[fid], new_f):
                modified.append(new_f)
            else:
                unchanged.append(fid)

        # 检查被移除的 finding
        for fid in old_map:
            if fid not in new_map:
                removed.append(fid)

        return {
            "added": added,
            "modified": modified,
            "unchanged": unchanged,
            "removed": removed,
        }

    @staticmethod
    def diff_to_toon(diff: dict[str, Any]) -> str:
        """将 Diff 结果序列化为 TOON 格式

        Args:
            diff: Diff 结果字典

        Returns:
            TOON 格式字符串
        """
        lines = ["diff{"]

        added = diff.get("added", [])
        if added:
            toon = TOONSerializer.findings_to_toon(added, fields=["id", "claim", "confidence", "evidence", "source"])
            # 保留完整 TOON 头部用于反序列化
            lines.append(f"  added[{len(added)}]:")
            for dl in toon.split("\n"):
                lines.append(f"    {dl.strip()}")

        modified = diff.get("modified", [])
        if modified:
            toon = TOONSerializer.findings_to_toon(modified, fields=["id", "claim", "confidence", "evidence", "source"])
            lines.append(f"  modified[{len(modified)}]:")
            for dl in toon.split("\n"):
                lines.append(f"    {dl.strip()}")

        unchanged = diff.get("unchanged", [])
        if unchanged:
            lines.append(f"  unchanged[{len(unchanged)}]: {','.join(unchanged)}")

        removed = diff.get("removed", [])
        if removed:
            lines.append(f"  removed[{len(removed)}]: {','.join(removed)}")

        lines.append("}")

        return "\n".join(lines)

    @staticmethod
    def toon_to_diff(data: str) -> dict[str, Any]:
        """从 TOON 格式反序列化为 Diff 结果

        Args:
            data: TOON 格式字符串

        Returns:
            Diff 结果字典
        """
        result: dict[str, Any] = {
            "added": [],
            "modified": [],
            "unchanged": [],
            "removed": [],
        }

        lines = [l.rstrip() for l in data.strip().split("\n") if l.strip()]
        section = None
        section_lines: list[str] = []

        for line in lines:
            if line == "diff{" or line == "}":
                # 保存上一个 section
                if section and section_lines:
                    if section in ("added", "modified"):
                        # 重新构造 TOON 格式
                        toon_data = "findings[0]{}:\n" + "\n".join(section_lines)
                        try:
                            result[section] = TOONSerializer.toon_to_findings(toon_data)
                        except Exception:
                            result[section] = []
                    elif section == "unchanged":
                        ids_str = ",".join(section_lines)
                        result[section] = [id.strip() for id in ids_str.split(",") if id.strip()]
                    elif section == "removed":
                        ids_str = ",".join(section_lines)
                        result[section] = [id.strip() for id in ids_str.split(",") if id.strip()]
                section = None
                section_lines = []
                continue

            if line.startswith("  added["):
                section = "added"
                section_lines = []
            elif line.startswith("  modified["):
                section = "modified"
                section_lines = []
            elif line.startswith("  unchanged["):
                section = "unchanged"
                # 格式: unchanged[N]: f1,f2
                if ":" in line:
                    ids_part = line.split(":", 1)[1].strip()
                    result["unchanged"] = [id.strip() for id in ids_part.split(",") if id.strip()]
                section = None
            elif line.startswith("  removed["):
                section = "removed"
                if ":" in line:
                    ids_part = line.split(":", 1)[1].strip()
                    result["removed"] = [id.strip() for id in ids_part.split(",") if id.strip()]
                section = None
            elif section and line.startswith("    "):
                section_lines.append(line[4:])

        return result

    @staticmethod
    def apply_diff(base_findings: list[dict[str, Any]], diff: dict[str, Any]) -> list[dict[str, Any]]:
        """将 Diff 应用到基础 finding 列表

        Args:
            base_findings: 基础 finding 列表
            diff: Diff 结果

        Returns:
            更新后的 finding 列表
        """
        result_map = {f.get("id", f.get("finding_id", "")): f for f in base_findings}

        # 移除
        for fid in diff.get("removed", []):
            if fid in result_map:
                del result_map[fid]

        # 添加
        for f in diff.get("added", []):
            fid = f.get("id", f.get("finding_id", ""))
            if fid:
                result_map[fid] = f

        # 修改
        for f in diff.get("modified", []):
            fid = f.get("id", f.get("finding_id", ""))
            if fid:
                result_map[fid] = f

        return list(result_map.values())

    @staticmethod
    def _is_different(old_f: dict[str, Any], new_f: dict[str, Any]) -> bool:
        """判断两个 finding 是否不同

        比较 claim、evidence、confidence、source 字段。
        """
        keys = ["claim", "evidence", "confidence", "source"]
        for k in keys:
            if old_f.get(k) != new_f.get(k):
                return True
        return False

    @staticmethod
    def estimate_savings(old_findings: list[dict[str, Any]], new_findings: list[dict[str, Any]]) -> dict[str, Any]:
        """估算 Diff 传输相比完整列表节省的 Token

        Args:
            old_findings: 旧列表
            new_findings: 新列表

        Returns:
            节省统计
        """
        import json

        diff = FindingDiffEngine.compute_diff(old_findings, new_findings)
        diff_toon = FindingDiffEngine.diff_to_toon(diff)
        full_toon = TOONSerializer.findings_to_toon(new_findings)
        full_json = json.dumps(new_findings, ensure_ascii=False)

        return {
            "old_count": len(old_findings),
            "new_count": len(new_findings),
            "added": len(diff["added"]),
            "modified": len(diff["modified"]),
            "unchanged": len(diff["unchanged"]),
            "removed": len(diff["removed"]),
            "diff_chars": len(diff_toon),
            "full_toon_chars": len(full_toon),
            "full_json_chars": len(full_json),
            "savings_vs_full_toon": len(full_toon) - len(diff_toon),
            "savings_vs_full_toon_percent": round((len(full_toon) - len(diff_toon)) / len(full_toon) * 100, 1) if full_toon else 0,
            "savings_vs_full_json": len(full_json) - len(diff_toon),
            "savings_vs_full_json_percent": round((len(full_json) - len(diff_toon)) / len(full_json) * 100, 1) if full_json else 0,
        }