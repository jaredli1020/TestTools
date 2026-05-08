"""通知器插件

内置：
- ConsoleNotifier：控制台打印
- FeishuWebhookNotifier：飞书群机器人 webhook
"""

from .console import ConsoleNotifier
from .feishu import FeishuWebhookNotifier

__all__ = ["ConsoleNotifier", "FeishuWebhookNotifier"]
