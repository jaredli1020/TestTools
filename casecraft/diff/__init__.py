"""Git Diff 分析器 - 基于代码变更产出回归测试上下文

抽象类 DiffAnalyzer 定义行为，内置 GitDiffAnalyzer 提供基于 git 的实现。
业务可扩展实现专属的影响面追踪（如调用链、依赖图）。
"""

from .base import DiffResult, DiffAnalyzer
from .git_diff import GitDiffAnalyzer

__all__ = ["DiffResult", "DiffAnalyzer", "GitDiffAnalyzer"]
