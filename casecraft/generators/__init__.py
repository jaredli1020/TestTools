"""用例生成器插件

内置：
- LLMCaseGenerator：通过 Anthropic API 生成用例（默认）

业务可注册自定义 Generator（如规则匹配、用例模板复用等）。
"""

from .llm import LLMCaseGenerator

__all__ = ["LLMCaseGenerator"]
