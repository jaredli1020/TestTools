"""Git Diff 分析器抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DiffResult:
    """Git diff 分析结果"""

    diff_ref: str = ""
    changed_files: list[dict] = field(default_factory=list)
    changed_methods: list[dict] = field(default_factory=list)
    affected_routes: list[dict] = field(default_factory=list)
    impact_chain: list[dict] = field(default_factory=list)
    summary: str = ""

    def format(self) -> str:
        """格式化为 LLM 可读的文本"""
        lines = [f"# Git Diff 变更分析 ({self.diff_ref})", ""]
        if self.changed_files:
            lines.append("## 变更文件")
            for f in self.changed_files[:30]:
                lines.append(f"- `{f.get('path', '')}` (+{f.get('added', 0)}/-{f.get('deleted', 0)})")
            lines.append("")

        if self.changed_methods:
            lines.append("## 变更方法")
            for m in self.changed_methods[:30]:
                lines.append(f"- `{m.get('file', '')}::{m.get('method', '')}`")
            lines.append("")

        if self.affected_routes:
            lines.append("## 受影响路由/接口")
            for r in self.affected_routes[:30]:
                lines.append(f"- {r.get('method', '')} {r.get('path', '')}")
            lines.append("")

        if self.impact_chain:
            lines.append("## 调用链影响")
            for i in self.impact_chain[:20]:
                lines.append(f"- {i.get('from', '')} -> {i.get('to', '')}")
            lines.append("")

        if self.summary:
            lines.append("## 总结")
            lines.append(self.summary)

        return "\n".join(lines)


class DiffAnalyzer(ABC):
    """Git Diff 分析器抽象基类"""

    name: str = ""

    @abstractmethod
    def analyze(self, project: dict, *, diff_ref: str = "HEAD~1", **kwargs) -> DiffResult:
        ...
