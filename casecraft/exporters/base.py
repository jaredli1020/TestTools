"""导出器基类和公共模板字段定义"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from casecraft.core import CaseExporter, TestCase, get_config


DEFAULT_HEADERS = [
    "模块", "用例标题", "优先级", "用例类型", "前置条件",
    "操作步骤", "预期结果", "测试数据", "实际结果", "关联接口",
    "标签", "用例来源", "状态", "备注", "创建人", "执行人",
]


class BaseExporter(CaseExporter):
    """导出器基类，统一输出目录、文件名、字段填充"""

    headers: list[str] = DEFAULT_HEADERS
    filename_prefix: str = "测试用例"

    def __init__(self, headers: list[str] | None = None, *,
                 filename_prefix: str | None = None):
        if headers is not None:
            self.headers = headers
        if filename_prefix is not None:
            self.filename_prefix = filename_prefix

    def _resolve_output(self, output_path: str | None) -> str:
        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
            return output_path
        out_dir = get_config().output.output_dir
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(out_dir, f"{self.filename_prefix}_{ts}.{self.extension}")

    @staticmethod
    def _fill_defaults(case: TestCase, creator: str = "casecraft") -> dict:
        d = dict(case.data)
        d.setdefault("实际结果", "")
        d.setdefault("状态", "未执行")
        d.setdefault("备注", "")
        d.setdefault("创建人", creator)
        d.setdefault("执行人", "")
        return d

    def _normalize(self, cases: Iterable[TestCase], creator: str = "casecraft") -> list[dict]:
        return [self._fill_defaults(c, creator) for c in cases]
