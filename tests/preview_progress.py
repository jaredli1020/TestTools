r"""Read-only UI fixtures using the production assets, without models/checkpoints.

Run: .venv\Scripts\python.exe -X utf8 tests\preview_progress.py
Open: http://127.0.0.1:8123
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


STATIC = Path(__file__).resolve().parents[1] / "casecraft" / "web" / "static"
STAGES = [("parse", "解析需求", 15), ("analyze", "关联代码", 20),
          ("generate", "Codex 生成", 68), ("export", "整理导出", 92)]


def fixtures():
    tasks = []
    for index, (stage, label, progress) in enumerate(STAGES):
        tasks.append({
            "id": f"preview-{stage}", "source_mode": "text",
            "source": "# 进度展示测试需求\n仅供本地界面验证，不会调用模型。",
            "requirement_title": f"界面验证 · {label}", "stage": f"正在{label}",
            "status": "running", "stage_key": stage, "progress": progress,
            "completed_stages": [item[0] for item in STAGES[:index]],
            "skipped_stages": [], "requested_project": "code_auto",
            "request": {"source_mode": "text", "source": "# 进度展示测试需求",
                        "project": "code_auto", "formats": ["excel"]},
            "created_at": datetime.now().isoformat(), "finished_at": "",
            "case_count": 0, "cases": [], "output_files": {},
            "repository": {}, "timings": {}, "stats": {},
        })
    failed = {**tasks[2], "id": "preview-error", "status": "error",
              "requirement_title": "界面验证 · 失败状态", "stage": "生成失败",
              "error": "模拟错误，仅用于验证失败步骤展示。"}
    done = {**tasks[3], "id": "preview-done", "status": "done", "progress": 100,
            "requirement_title": "界面验证 · 完成状态", "stage": "生成完成",
            "stage_key": "complete", "completed_stages": [item[0] for item in STAGES],
            "finished_at": datetime.now().isoformat()}
    return {task["id"]: task for task in [*tasks, failed, done]}


TASKS = fixtures()


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/config":
            return self.respond({"projects": {"code_auto": {"label": "模拟关联代码", "auto": True}},
                                 "formats": ["excel", "xmind", "markdown", "json"],
                                 "generator": "codex", "llm": {"provider": "codex_cli",
                                 "model": "UI fixture", "reasoning_effort": "xhigh"}})
        if path == "/api/tasks":
            return self.respond(list(TASKS.values()))
        if path.startswith("/api/tasks/"):
            task = TASKS.get(path.split("/")[3])
            if task is None:
                return self.send_error(404)
            if path.endswith("/stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                payload = json.dumps(task, ensure_ascii=False)
                try:
                    self.wfile.write(f"event: update\ndata: {payload}\n\n".encode())
                    self.wfile.flush()
                    for _ in range(60):
                        time.sleep(2)
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                return
            return self.respond(task)
        if path.startswith("/api/"):
            return self.send_error(404)
        if path.startswith("/static/"):
            self.path = self.path.removeprefix("/static")
        return super().do_GET()

    def respond(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8123)
    options = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", options.port), PreviewHandler)
    print(f"Read-only UI preview: http://127.0.0.1:{options.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
