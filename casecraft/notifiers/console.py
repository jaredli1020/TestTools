"""控制台通知器 - 简单 stdout 输出，适合本地 CLI 使用"""

from casecraft.core import Notifier


class ConsoleNotifier(Notifier):
    name = "console"

    def on_start(self, task_name: str, **context):
        print(f"[START] {task_name}")

    def on_stage(self, task_name: str, stage: str, **context):
        print(f"[STAGE] {task_name} -> {stage}")

    def on_error(self, task_name: str, stage: str, error: str, **context):
        print(f"[ERROR] {task_name} @ {stage}: {error}")

    def on_finish(self, task_name: str, case_count: int, output_files: list, **context):
        print(f"[DONE]  {task_name} | 用例 {case_count} | 输出 {output_files}")
