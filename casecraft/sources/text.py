"""文本需求源 - 兜底处理器，接收任意字符串作为需求内容"""

from casecraft.core import RequirementSource, Requirement
from .titles import extract_requirement_title, is_local_path_reference


class TextSource(RequirementSource):
    name = "text"

    def match(self, source: str) -> bool:
        # 兜底处理器，任何字符串都能接受，但注册时应放在最后
        return True

    def parse(self, source: str, *, section: str | None = None, **kwargs) -> Requirement:
        if is_local_path_reference(source):
            raise ValueError("输入内容是文件路径，不是需求正文。请切换到“本地路径”并填写有效的需求文件路径。")
        title = kwargs.get("title") or extract_requirement_title(source)
        return Requirement(
            title=title,
            content=source,
            source_type="text",
            source_ref="",
        )
