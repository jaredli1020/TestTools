"""FastAPI 应用 - Web 骨架"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from casecraft.core import Pipeline, get_config, load_config, registry


app = FastAPI(title="casecraft", version="0.1.0")


# ==================== 任务状态 ====================

@dataclass
class TaskInfo:
    id: str
    source: str
    status: str = "pending"       # pending / running / done / error
    stage: str = "等待开始"
    progress: int = 0
    requirement_title: str = ""
    case_count: int = 0
    cases: list = field(default_factory=list)
    output_files: dict[str, str] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_tasks: dict[str, TaskInfo] = {}


# ==================== 请求模型 ====================

class GenRequest(BaseModel):
    source: str
    section: Optional[str] = None
    project: Optional[str] = None
    branch: Optional[str] = None
    skip_code: bool = False
    formats: list[str] = ["excel"]
    creator: str = "casecraft"
    extra_prompt: str = ""
    output_path: Optional[str] = None


# ==================== 生命周期 ====================

@app.on_event("startup")
def _startup():
    load_config()


# ==================== API ====================

@app.get("/api/config")
def api_config():
    cfg = get_config()
    projects = {k: {"type": v.get("type", "unknown"), "source": v.get("source", "local")}
                for k, v in cfg.projects.items()}
    return {
        "projects": projects,
        "formats": registry.list_exporters(),
        "notify_enabled": cfg.notify.enabled,
    }


@app.post("/api/generate")
def api_generate(req: GenRequest, background: BackgroundTasks):
    task_id = uuid.uuid4().hex[:12]
    task = TaskInfo(id=task_id, source=req.source)
    _tasks[task_id] = task
    background.add_task(_run_task, task_id, req)
    return {"task_id": task_id}


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task.to_dict()


@app.get("/api/tasks")
def api_task_list(limit: int = 30):
    tasks = sorted(_tasks.values(), key=lambda t: t.created_at, reverse=True)
    return [t.to_dict() for t in tasks[:limit]]


@app.get("/api/tasks/{task_id}/stream")
async def api_task_stream(task_id: str):
    if task_id not in _tasks:
        raise HTTPException(404, "任务不存在")

    async def event_generator():
        prev = None
        while True:
            task = _tasks.get(task_id)
            if not task:
                break
            payload = task.to_dict()
            if payload != prev:
                yield {"event": "update", "data": _json(payload)}
                prev = payload
            if task.status in ("done", "error"):
                break
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/api/tasks/{task_id}/download/{fmt}")
def api_download(task_id: str, fmt: str):
    task = _tasks.get(task_id)
    if not task or fmt not in task.output_files:
        raise HTTPException(404, "文件不存在")
    path = task.output_files[fmt]
    if not os.path.isfile(path):
        raise HTTPException(404, "文件已删除")
    return FileResponse(path, filename=os.path.basename(path))


# ==================== 内部执行 ====================

def _run_task(task_id: str, req: GenRequest):
    task = _tasks[task_id]
    task.status = "running"

    pipeline = Pipeline()
    listener = _WebListener(task)
    registry.register_listener(listener)

    try:
        result = pipeline.run(
            req.source,
            section=req.section,
            project=req.project,
            branch=req.branch,
            formats=req.formats,
            output_path=req.output_path,
            creator=req.creator,
            extra_prompt=req.extra_prompt,
            skip_code=req.skip_code,
            task_name=req.source[:60],
        )
        task.requirement_title = result.requirement.title if result.requirement else ""
        task.case_count = len(result.cases)
        task.cases = [c.to_dict() for c in result.cases]
        task.output_files = {
            _detect_format(p): p for p in result.output_files
        }
        task.stats = result.stats
        task.timings = result.timings
        task.status = "done"
        task.progress = 100
        task.stage = "完成"
    except Exception as e:
        task.status = "error"
        task.error = str(e)
    finally:
        task.finished_at = datetime.now().isoformat()
        if listener in registry.listeners:
            registry.listeners.remove(listener)


class _WebListener:
    """捕获管道阶段事件并更新任务状态"""

    STAGE_MAP = {
        "parse": ("解析需求", 20),
        "analyze": ("代码分析", 40),
        "generate": ("AI 生成用例", 80),
        "export": ("导出文件", 95),
    }

    def __init__(self, task: TaskInfo):
        self.task = task

    def on_stage_start(self, stage: str, **context):
        label, progress = self.STAGE_MAP.get(stage, (stage, self.task.progress))
        self.task.stage = label
        self.task.progress = progress

    def on_stage_end(self, stage: str, **context):
        pass

    def on_error(self, stage: str, error: Exception, **context):
        self.task.error = str(error)


def _detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    mapping = {"xlsx": "excel", "xmind": "xmind", "md": "markdown", "json": "json"}
    return mapping.get(ext, ext)


def _json(obj: Any) -> str:
    import json as _json_mod
    return _json_mod.dumps(obj, ensure_ascii=False)
