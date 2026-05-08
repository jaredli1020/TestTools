"""casecraft - 需求驱动的测试用例自动生成框架

插件化架构，支持自定义需求源、代码分析器、LLM 生成器、导出器、通知器。

核心流程：
    Requirement (需求) -> CodeContext (代码上下文) -> TestCases (用例) -> 导出/通知

业务项目通过注册 Source / Analyzer / Exporter 等插件扩展能力。
"""

__version__ = "0.1.0"
