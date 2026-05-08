"""插件注册表 - 统一管理所有插件实例

业务项目在启动时通过 registry.register() 挂载自己的插件，管道从中按类型
发现并调度。
"""

from __future__ import annotations

from typing import TypeVar

from .interfaces import (
    RequirementSource,
    CodeAnalyzer,
    CaseGenerator,
    CaseExporter,
    Notifier,
    StageListener,
)

T = TypeVar("T")


class Registry:
    """插件注册表，按类型收集插件实例"""

    def __init__(self):
        self.sources: list[RequirementSource] = []
        self.analyzers: list[CodeAnalyzer] = []
        self.generators: dict[str, CaseGenerator] = {}
        self.exporters: dict[str, CaseExporter] = {}
        self.notifiers: list[Notifier] = []
        self.listeners: list[StageListener] = []
        self._default_generator: str | None = None

    # ---------- register ----------

    def register_source(self, source: RequirementSource, *, front: bool = False):
        """front=True 插入头部，优先匹配"""
        if front:
            self.sources.insert(0, source)
        else:
            self.sources.append(source)

    def register_analyzer(self, analyzer: CodeAnalyzer, *, front: bool = False):
        if front:
            self.analyzers.insert(0, analyzer)
        else:
            self.analyzers.append(analyzer)

    def register_generator(self, generator: CaseGenerator, *, default: bool = False):
        if not generator.name:
            raise ValueError("CaseGenerator.name 不能为空")
        self.generators[generator.name] = generator
        if default or self._default_generator is None:
            self._default_generator = generator.name

    def register_exporter(self, exporter: CaseExporter):
        if not exporter.name:
            raise ValueError("CaseExporter.name 不能为空")
        self.exporters[exporter.name] = exporter

    def register_notifier(self, notifier: Notifier):
        self.notifiers.append(notifier)

    def register_listener(self, listener: StageListener):
        self.listeners.append(listener)

    # ---------- lookup ----------

    def find_source(self, input_str: str) -> RequirementSource:
        for src in self.sources:
            if src.match(input_str):
                return src
        raise LookupError(f"没有 RequirementSource 能处理输入: {input_str[:80]}")

    def find_analyzer(self, project: dict) -> CodeAnalyzer | None:
        for ana in self.analyzers:
            if ana.match(project):
                return ana
        return None

    def get_generator(self, name: str | None = None) -> CaseGenerator:
        key = name or self._default_generator
        if not key or key not in self.generators:
            raise LookupError(f"未注册 Generator: {name}")
        return self.generators[key]

    def get_exporter(self, name: str) -> CaseExporter:
        if name not in self.exporters:
            raise LookupError(f"未注册 Exporter: {name}")
        return self.exporters[name]

    def list_exporters(self) -> list[str]:
        return list(self.exporters.keys())

    # ---------- clear / reset ----------

    def reset(self):
        self.sources.clear()
        self.analyzers.clear()
        self.generators.clear()
        self.exporters.clear()
        self.notifiers.clear()
        self.listeners.clear()
        self._default_generator = None


registry = Registry()
