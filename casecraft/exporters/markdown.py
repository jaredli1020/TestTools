"""Markdown 导出器 - 按模块分组，适合飞书/GitHub/Notion 阅读"""

from __future__ import annotations

from typing import Iterable

from casecraft.core import TestCase

from .base import BaseExporter


PRIORITY_ICON = {"P0": "🔴", "P1": "🟠", "P2": "🔵", "P3": "⚪"}
TAG_ICON = {"正常流程": "✅", "异常": "❌", "边界值": "⚠️", "权限": "🔒"}


class MarkdownExporter(BaseExporter):
    name = "markdown"
    extension = "md"

    def export(self, cases: Iterable[TestCase], output_path: str | None = None, **kwargs) -> str:
        output_path = self._resolve_output(output_path)
        rows = [c.data for c in cases]

        priorities: dict[str, int] = {}
        tags: dict[str, int] = {}
        modules: dict[str, list[dict]] = {}
        for r in rows:
            priorities[r.get("优先级", "未知")] = priorities.get(r.get("优先级", "未知"), 0) + 1
            tags[r.get("标签", "未知")] = tags.get(r.get("标签", "未知"), 0) + 1
            modules.setdefault(r.get("模块", "未分类"), []).append(r)

        lines = [
            "# 测试用例",
            "",
            f"共 {len(rows)} 条用例",
            "",
            "## 概览",
            "",
            "### 优先级分布",
            "",
        ]
        for p in ("P0", "P1", "P2", "P3"):
            if p in priorities:
                lines.append(f"- {PRIORITY_ICON.get(p, '')} {p}: **{priorities[p]}** 条")
        lines += ["", "### 标签分布", ""]
        for t, c in tags.items():
            lines.append(f"- {TAG_ICON.get(t, '')} {t}: **{c}** 条")

        lines.append("")
        for module_name, module_cases in modules.items():
            lines.append(f"## 📁 {module_name} ({len(module_cases)})")
            lines.append("")
            for case in module_cases:
                priority = case.get("优先级", "P2")
                p_icon = PRIORITY_ICON.get(priority, "")
                title = case.get("用例标题", "")
                lines.append(f"### {p_icon} [{priority}] {title}")
                lines.append("")

                meta_parts = []
                if case.get("用例类型"):
                    meta_parts.append(f"**类型**: {case['用例类型']}")
                if case.get("标签"):
                    meta_parts.append(f"**标签**: {TAG_ICON.get(case['标签'], '')} {case['标签']}")
                if case.get("用例来源"):
                    meta_parts.append(f"**来源**: {case['用例来源']}")
                if meta_parts:
                    lines.append(" | ".join(meta_parts))
                    lines.append("")

                if case.get("前置条件"):
                    lines += ["**前置条件**:", "", f"> {case['前置条件']}", ""]
                if case.get("操作步骤"):
                    lines.append("**操作步骤**:")
                    lines.append("")
                    for i, step in enumerate(case["操作步骤"].split("\n"), 1):
                        step = step.strip()
                        if step:
                            lines.append(f"{i}. {step}")
                    lines.append("")
                if case.get("预期结果"):
                    lines += ["**预期结果**:", "", f"> {case['预期结果']}", ""]
                if case.get("测试数据"):
                    lines += ["**测试数据**:", "", "```", case["测试数据"], "```", ""]
                if case.get("关联接口"):
                    lines += [f"**关联接口**: `{case['关联接口']}`", ""]
                if case.get("备注"):
                    lines += [f"**备注**: {case['备注']}", ""]

                lines.append("---")
                lines.append("")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return output_path
