"""代码分析器插件

内置：
- LocalGitAnalyzer：自动识别、安全同步并提取本地 Git 仓库代码
- NoopAnalyzer：占位实现，跳过代码分析（适合纯需求 -> 用例场景）

业务项目可继承 CodeAnalyzer 实现 PHP/Java/Go/Python 等语言的分析器。
"""

from .noop import NoopAnalyzer
from .local_git import LocalGitAnalyzer, RepositorySyncError

__all__ = ["LocalGitAnalyzer", "NoopAnalyzer", "RepositorySyncError"]
