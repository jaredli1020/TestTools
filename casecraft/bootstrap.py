"""框架引导 - 快速初始化默认插件

业务在 bootstrap 后再追加自己的插件，不需要手动注册每一个内置插件。
"""

from __future__ import annotations

from .core import registry
from .sources import TextSource, FileSource
from .analyzers import NoopAnalyzer
from .generators import LLMCaseGenerator
from .exporters import ExcelExporter, XMindExporter, MarkdownExporter, JsonExporter
from .notifiers import ConsoleNotifier


_bootstrapped = False


def bootstrap_defaults(
    *,
    include_console_notifier: bool = False,
    llm_generator: bool = True,
) -> None:
    """注册框架默认插件

    Args:
        include_console_notifier: 是否注册控制台通知器（适合 CLI）
        llm_generator: 是否注册 LLM 生成器（需要 anthropic SDK）
    """
    global _bootstrapped
    if _bootstrapped:
        return

    # Sources - text 放最后兜底
    registry.register_source(FileSource())
    registry.register_source(TextSource())

    # Analyzers - noop 放最后兜底
    registry.register_analyzer(NoopAnalyzer())

    # Generators
    if llm_generator:
        registry.register_generator(LLMCaseGenerator(), default=True)

    # Exporters
    registry.register_exporter(ExcelExporter())
    registry.register_exporter(XMindExporter())
    registry.register_exporter(MarkdownExporter())
    registry.register_exporter(JsonExporter())

    # Notifiers
    if include_console_notifier:
        registry.register_notifier(ConsoleNotifier())

    _bootstrapped = True


def reset():
    """重置注册表（主要用于测试）"""
    global _bootstrapped
    registry.reset()
    _bootstrapped = False
