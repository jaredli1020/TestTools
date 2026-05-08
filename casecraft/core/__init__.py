"""框架核心数据模型 + 抽象基类 + 插件注册 + 管道编排"""

from .models import Requirement, CodeContext, TestCase
from .interfaces import (
    RequirementSource,
    CodeAnalyzer,
    CaseGenerator,
    CaseExporter,
    Notifier,
    StageListener,
)
from .registry import Registry, registry
from .pipeline import Pipeline, PipelineResult
from .config import Config, load_config, get_config

__all__ = [
    "Requirement",
    "CodeContext",
    "TestCase",
    "RequirementSource",
    "CodeAnalyzer",
    "CaseGenerator",
    "CaseExporter",
    "Notifier",
    "StageListener",
    "Registry",
    "registry",
    "Pipeline",
    "PipelineResult",
    "Config",
    "load_config",
    "get_config",
]
