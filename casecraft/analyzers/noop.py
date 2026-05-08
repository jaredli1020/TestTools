"""占位代码分析器 - 默认跳过代码分析，返回空上下文"""

from casecraft.core import CodeAnalyzer, CodeContext, Requirement


class NoopAnalyzer(CodeAnalyzer):
    name = "noop"

    def match(self, project: dict) -> bool:
        # 永远返回 True，注册时放在最后作为兜底
        return True

    def analyze(self, requirement: Requirement, project: dict, **kwargs) -> CodeContext:
        return CodeContext(
            project_key=project.get("key", ""),
            project_type=project.get("type", ""),
            content="",
        )
