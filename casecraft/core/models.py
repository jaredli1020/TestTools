"""核心数据模型 - 框架内部流转的标准化数据结构

所有插件（Source、Analyzer、Generator、Exporter）都围绕这三个模型协作，
互不耦合。字段尽量开放（extras dict），方便业务插件附加元数据。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Requirement:
    """需求 - 由 RequirementSource 解析后产出，作为管道的第一个产物"""

    title: str
    content: str
    source_type: str = "text"       # text / file / feishu_doc / confluence / ...
    source_ref: str = ""            # URL / file path / doc_id 等原始引用
    images: list = field(default_factory=list)
    comments: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    def preview(self, limit: int = 200) -> str:
        return self.content[:limit].replace("\n", " ") + ("..." if len(self.content) > limit else "")


@dataclass
class CodeContext:
    """代码上下文 - 由 CodeAnalyzer 产出，作为 LLM 生成用例的辅助输入

    content 是 LLM 可直接消费的 Markdown/文本格式；raw 保留结构化数据
    方便 Summarizer / 二次加工消费。
    """

    content: str = ""
    project_key: str = ""
    project_type: str = ""
    branch: str = ""
    raw: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.content.strip()


@dataclass
class TestCase:
    """测试用例 - Generator 产出，Exporter 消费

    data 字段完全开放，由 Generator 按项目模板填充。常见字段：
    模块/用例标题/优先级/用例类型/前置条件/操作步骤/预期结果/测试数据/
    关联接口/标签/用例来源/备注 等
    """

    data: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = "") -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any):
        self.data[key] = value

    @classmethod
    def from_dict(cls, d: dict) -> "TestCase":
        return cls(data=dict(d))

    def to_dict(self) -> dict:
        return dict(self.data)
