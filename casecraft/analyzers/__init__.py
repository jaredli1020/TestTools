"""代码分析器插件

内置：
- NoopAnalyzer：占位实现，跳过代码分析（适合纯需求 -> 用例场景）

业务项目可继承 CodeAnalyzer 实现 PHP/Java/Go/Python 等语言的分析器。
"""

from .noop import NoopAnalyzer

__all__ = ["NoopAnalyzer"]
