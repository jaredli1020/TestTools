"""飞书群机器人通知器 - webhook 卡片消息"""

from __future__ import annotations

import os
import time
from datetime import datetime

import requests

from casecraft.core import Notifier


class FeishuWebhookNotifier(Notifier):
    """通过飞书群机器人 webhook 发送卡片通知"""

    name = "feishu_webhook"

    def __init__(self, webhook_url: str, *, send_heartbeat: bool = True):
        self.webhook_url = webhook_url
        self.send_heartbeat_enabled = send_heartbeat
        self._task_start: dict[str, float] = {}

    # ---------- 卡片工具 ----------

    def _send_card(self, title: str, lines: list[str], color: str = "blue") -> bool:
        if not self.webhook_url:
            return False
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": color,
                },
                "elements": [
                    {"tag": "markdown", "content": "\n".join(lines)},
                ],
            },
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    # ---------- Notifier hooks ----------

    def on_start(self, task_name: str, **context):
        self._task_start[task_name] = time.time()
        self._send_card(
            "🚀 casecraft 任务开始",
            [
                f"**任务:** {task_name}",
                f"**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "**状态:** 开始执行",
            ],
            color="blue",
        )

    def on_error(self, task_name: str, stage: str, error: str, **context):
        elapsed = int(time.time() - self._task_start.get(task_name, time.time()))
        self._send_card(
            "❌ casecraft 任务失败",
            [
                f"**任务:** {task_name}",
                f"**阶段:** {stage}",
                f"**耗时:** {elapsed}s",
                f"**错误:** {error}",
            ],
            color="red",
        )

    def on_heartbeat(self, task_name: str, stage: str, elapsed: float, idle: float, **context):
        if not self.send_heartbeat_enabled:
            return
        self._send_card(
            "💓 casecraft 执行中",
            [
                f"**任务:** {task_name}",
                f"**当前阶段:** {stage}",
                f"**已运行:** {int(elapsed)}s",
                f"**阶段耗时:** {int(idle)}s",
            ],
            color="orange",
        )

    def on_finish(self, task_name: str, case_count: int, output_files: list[str], **context):
        elapsed = int(time.time() - self._task_start.get(task_name, time.time()))
        lines = [
            f"**任务:** {task_name}",
            f"**耗时:** {elapsed}s",
            f"**用例数:** {case_count} 条",
        ]
        if output_files:
            lines.append("")
            for fpath in output_files:
                if os.path.isfile(fpath):
                    lines.append(f"📎 `{os.path.abspath(fpath)}`")
        self._send_card("✅ casecraft 任务完成", lines, color="green")
