"""文本需求源 - 兜底处理器，接收任意字符串作为需求内容"""

from casecraft.core import RequirementSource, Requirement


class TextSource(RequirementSource):
    name = "text"

    def match(self, source: str) -> bool:
        # 兜底处理器，任何字符串都能接受，但注册时应放在最后
        return True

    def parse(self, source: str, *, section: str | None = None, **kwargs) -> Requirement:
        title = kwargs.get("title", "需求文本")
        return Requirement(
            title=title,
            content=source,
            source_type="text",
            source_ref="",
        )
