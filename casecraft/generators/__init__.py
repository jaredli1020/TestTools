"""用例生成器插件

内置：
- CodexCaseGenerator：通过 OpenAI Responses API 生成用例（默认）
- LLMCaseGenerator：CodexCaseGenerator 的兼容别名

业务可注册自定义 Generator（如规则匹配、用例模板复用等）。
"""

from .llm import CodexCaseGenerator, LLMCaseGenerator

__all__ = ["CodexCaseGenerator", "LLMCaseGenerator"]
