"""插件接口 - 所有扩展点的抽象基类

业务项目继承这些基类，通过 registry.register() 注册，管道自动发现和调度。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .models import Requirement, CodeContext, TestCase


class RequirementSource(ABC):
    """需求源插件 - 识别并解析不同来源的需求输入（文本、文件、飞书文档等）"""

    #: 插件唯一名称，用于日志和配置引用
    name: str = ""

    @abstractmethod
    def match(self, source: str) -> bool:
        """判断是否能处理该输入源"""

    @abstractmethod
    def parse(self, source: str, *, section: str | None = None, **kwargs) -> Requirement:
        """解析并返回 Requirement"""


class CodeAnalyzer(ABC):
    """代码分析器插件 - 根据需求从代码库提取相关上下文"""

    name: str = ""

    @abstractmethod
    def match(self, project: dict) -> bool:
        """判断能否处理该项目（通常根据 project["type"] 匹配）"""

    @abstractmethod
    def analyze(self, requirement: Requirement, project: dict, **kwargs) -> CodeContext:
        """分析代码并返回 CodeContext"""


class CaseGenerator(ABC):
    """用例生成器插件 - 基于 Requirement + CodeContext 生成测试用例

    框架内置 CodexCaseGenerator，业务可以实现其他 Generator（如规则生成、
    历史用例复用等）。
    """

    name: str = ""

    @abstractmethod
    def generate(self, requirement: Requirement, code_context: CodeContext | None = None,
                 *, extra_prompt: str = "", **kwargs) -> list[TestCase]:
        ...


class CaseExporter(ABC):
    """导出器插件 - 把 TestCase 列表写出到文件/平台"""

    name: str = ""
    extension: str = ""      # 文件扩展名，如 "xlsx" / "xmind" / "md"

    @abstractmethod
    def export(self, cases: Iterable[TestCase], output_path: str | None = None,
               **kwargs) -> str:
        """导出并返回生成的文件路径"""


class Notifier(ABC):
    """通知器插件 - 任务开始/进行中/完成/失败的消息通知"""

    name: str = ""

    def on_start(self, task_name: str, **context):
        pass

    def on_stage(self, task_name: str, stage: str, **context):
        pass

    def on_heartbeat(self, task_name: str, stage: str, elapsed: float, idle: float, **context):
        pass

    def on_error(self, task_name: str, stage: str, error: str, **context):
        pass

    def on_finish(self, task_name: str, case_count: int, output_files: list[str], **context):
        pass


class StageListener(ABC):
    """管道阶段监听器 - 用于进度推送、日志埋点、监控

    对比 Notifier：Notifier 面向外部通知渠道，Listener 更偏向程序级 hook，
    例如 Web 前端 SSE 推送或 CLI 进度条。
    """

    def on_stage_start(self, stage: str, **context):
        pass

    def on_stage_end(self, stage: str, **context):
        pass

    def on_error(self, stage: str, error: Exception, **context):
        pass
