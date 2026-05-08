"""需求源插件 - 解析各种来源的需求

内置插件：
- TextSource：直接传入的文本
- FileSource：本地文件（.md / .txt / .json）

可选插件（需要对应依赖）：
- feishu.FeishuDocSource：飞书文档（需要 lark-oapi）
"""

from .text import TextSource
from .file import FileSource

__all__ = ["TextSource", "FileSource"]
