"""JSON 导出器 - 保留所有字段便于二次处理"""

from __future__ import annotations

import json
from typing import Iterable

from casecraft.core import TestCase

from .base import BaseExporter


class JsonExporter(BaseExporter):
    name = "json"
    extension = "json"

    def export(self, cases: Iterable[TestCase], output_path: str | None = None,
               creator: str = "casecraft", **kwargs) -> str:
        output_path = self._resolve_output(output_path)
        rows = self._normalize(cases, creator)

        full_cases = []
        for row in rows:
            full_case = {h: row.get(h, "") for h in self.headers}
            # 补齐 headers 之外的额外字段
            for k, v in row.items():
                full_case.setdefault(k, v)
            full_cases.append(full_case)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(full_cases, f, ensure_ascii=False, indent=2)

        return output_path
