"""XMind 导出器 - 输出 XMind 8+ 兼容的 .xmind 文件（ZIP + JSON）"""

from __future__ import annotations

import json
import uuid
import zipfile
from typing import Iterable

from casecraft.core import TestCase

from .base import BaseExporter


class XMindExporter(BaseExporter):
    name = "xmind"
    extension = "xmind"

    def export(self, cases: Iterable[TestCase], output_path: str | None = None, **kwargs) -> str:
        output_path = self._resolve_output(output_path)
        rows = [c.data for c in cases]

        # 按模块分组
        modules: dict[str, list[dict]] = {}
        for row in rows:
            modules.setdefault(row.get("模块", "未分类"), []).append(row)

        module_topics = []
        for module_name, module_cases in modules.items():
            case_topics = []
            for case in module_cases:
                priority = case.get("优先级", "P2")
                tag = case.get("标签", "")
                case_type = case.get("用例类型", "")
                source = case.get("用例来源", "")
                title = f"[{priority}] {case.get('用例标题', '')}"
                if tag:
                    title += f" ({tag})"

                children = []
                if case_type:
                    children.append(_topic(f"类型: {case_type}"))

                steps = case.get("操作步骤", "")
                if steps:
                    step_children = []
                    for i, step in enumerate(steps.split("\n"), 1):
                        step = step.strip()
                        if step:
                            step_children.append(_topic(f"{i}. {step}"))
                    children.append(_topic("操作步骤", step_children))

                if case.get("预期结果"):
                    children.append(_topic(f"预期: {case['预期结果']}"))
                if case.get("关联接口"):
                    children.append(_topic(f"接口: {case['关联接口']}"))
                if source:
                    children.append(_topic(f"来源: {source}"))
                if case.get("备注"):
                    children.append(_topic(f"备注: {case['备注']}"))

                case_topics.append(_topic(title, children))

            module_topics.append(_topic(f"📁 {module_name}", case_topics))

        root = _topic("测试用例", module_topics)
        sheet_id = _gen_id()

        content_json = [{"id": sheet_id, "class": "sheet", "title": "测试用例", "rootTopic": root}]
        metadata_json = {"creator": {"name": "casecraft", "version": "1.0"}, "activeSheetId": sheet_id}
        manifest_json = {"file-entries": {"content.json": {}, "metadata.json": {}}}

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("content.json", json.dumps(content_json, ensure_ascii=False, indent=2))
            zf.writestr("metadata.json", json.dumps(metadata_json, ensure_ascii=False))
            zf.writestr("manifest.json", json.dumps(manifest_json, ensure_ascii=False))

        return output_path


def _gen_id() -> str:
    return uuid.uuid4().hex[:24]


def _topic(title: str, children: list[dict] | None = None) -> dict:
    node = {"id": _gen_id(), "title": title}
    if children:
        node["children"] = {"attached": children}
    return node
