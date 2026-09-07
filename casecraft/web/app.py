"""CaseCraft 本地 Web 工作台。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from casecraft.bootstrap import bootstrap_defaults
from casecraft.core import Pipeline, get_config, load_config, registry
from casecraft.sources import FileSource, MongosoShareSource
from casecraft.sources.titles import is_local_path_reference


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
CHECKPOINT_DIR = PROJECT_ROOT / ".task_checkpoints"
UPLOAD_DIR = PROJECT_ROOT / ".uploaded_requirements"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

app = FastAPI(
    title="CaseCraft",
    description="需求驱动的测试用例生成工作台",
    version="0.2.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@dataclass
class TaskInfo:
    id: str
    source: str
    source_mode: str = "text"
    requested_project: str = ""
    request: dict = field(default_factory=dict)
    status: str = "pending"
    stage: str = "等待执行"
    stage_key: str = ""
    completed_stages: list[str] = field(default_factory=list)
    skipped_stages: list[str] = field(default_factory=list)
    warning: str = ""
    progress: int = 0
    requirement_title: str = ""
    case_count: int = 0
    cases: list = field(default_factory=list)
    output_files: dict[str, str] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    repository: dict = field(default_factory=dict)
    routing: dict = field(default_factory=dict)
    requirement_source: dict = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""

    def to_dict(self, *, include_cases: bool = True) -> dict:
        payload = asdict(self)
        if not include_cases:
            payload["cases"] = []
        payload["source_preview"] = _source_preview(self.source)
        payload["download_names"] = {
            fmt: _download_filename(self, path) for fmt, path in self.output_files.items()
        }
        return payload


_tasks: dict[str, TaskInfo] = {}
_tasks_lock = threading.RLock()
_pipeline_lock = threading.Lock()


class GenRequest(BaseModel):
    source: str
    source_mode: Literal["text", "path", "link"] = "text"
    section: Optional[str] = None
    project: Optional[str] = None
    branch: Optional[str] = None
    skip_code: bool = False
    formats: list[str] = Field(default_factory=lambda: ["excel"])
    creator: str = "casecraft"
    extra_prompt: str = ""
    case_scope: Literal["all", "core"] = "all"
    output_path: Optional[str] = None


@app.on_event("startup")
def _startup():
    load_config()
    bootstrap_defaults()
    _load_checkpoints()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/health")
def api_health():
    return {"status": "ok", "service": "casecraft"}


@app.post("/api/uploads")
async def api_upload_requirement(file: UploadFile = File(...)):
    """Persist a browser-selected, supported text requirement for local parsing."""
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in FileSource.SUPPORTED_EXTS:
        raise HTTPException(422, "仅支持 .md、.txt、.json、.markdown 和 .rst 需求文件")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(422, "上传的需求文件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(422, "需求文件不能超过 2 MB")
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "需求文件必须是 UTF-8 文本格式") from exc

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    temporary = target.with_suffix(f"{suffix}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, target)
    return {"source": str(target.resolve()), "filename": filename, "size": len(content)}


@app.get("/api/config")
def api_config():
    cfg = get_config()
    projects = {
        key: {
            "type": value.get("type", "unknown"),
            "source": value.get("source", "local"),
            "label": value.get("label", key),
            "description": value.get("description", ""),
            "framework": value.get("framework", ""),
            "auto": value.get("type") == "auto-local-git",
        }
        for key, value in cfg.projects.items()
        if value.get("selectable", True)
    }
    return {
        "projects": projects,
        "formats": registry.list_exporters(),
        "generator": registry.get_generator().name,
        "llm": {
            "provider": cfg.llm.provider,
            "model": cfg.llm.model,
            "reasoning_effort": cfg.llm.reasoning_effort,
            "api_key_configured": bool(cfg.llm.api_key),
        },
        "notify_enabled": cfg.notify.enabled,
    }


@app.post("/api/generate", status_code=202)
def api_generate(req: GenRequest, background: BackgroundTasks):
    source = req.source.strip()
    if not source:
        raise HTTPException(422, "请输入需求内容或本地文件路径")
    if req.source_mode == "link" and not MongosoShareSource.extract_item_id(source):
        raise HTTPException(
            422,
            "请输入有效的 Mongoso 需求分享链接，格式为 "
            "https://max.mongoso.com/share?itemid=...",
        )
    if req.source_mode == "path":
        try:
            FileSource.resolve_path(source)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
    elif req.source_mode == "text" and is_local_path_reference(source):
        raise HTTPException(422, "输入内容是文件路径，请切换到“本地路径”，不要将文件地址当作需求正文。")

    available_formats = set(registry.list_exporters())
    requested_formats = list(dict.fromkeys(req.formats))
    invalid_formats = set(requested_formats) - available_formats
    if not requested_formats:
        raise HTTPException(422, "请至少选择一种导出格式")
    if invalid_formats:
        raise HTTPException(422, f"不支持的导出格式: {', '.join(sorted(invalid_formats))}")

    req.source = source
    req.formats = requested_formats
    task_id = uuid.uuid4().hex[:12]
    task = TaskInfo(
        id=task_id,
        source=source,
        source_mode=req.source_mode,
        requested_project=req.project or "",
        request=req.model_dump(),
    )
    with _tasks_lock:
        _tasks[task_id] = task
        _persist_task(task)
    background.add_task(_run_task, task_id, req)
    return {"task_id": task_id}


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str):
    return _get_task(task_id).to_dict()


@app.get("/api/tasks")
def api_task_list(limit: int = Query(default=30, ge=1, le=100)):
    with _tasks_lock:
        tasks = sorted(_tasks.values(), key=lambda task: task.created_at, reverse=True)
        return [task.to_dict(include_cases=False) for task in tasks[:limit]]


@app.delete("/api/tasks/{task_id}", status_code=204)
def api_task_delete(task_id: str):
    task = _get_task(task_id)
    if task.status in {"pending", "running"}:
        raise HTTPException(409, "运行中的任务不能删除")
    with _tasks_lock:
        _tasks.pop(task_id, None)
        _checkpoint_path(task_id).unlink(missing_ok=True)


@app.get("/api/tasks/{task_id}/stream")
async def api_task_stream(task_id: str):
    _get_task(task_id)

    async def event_generator():
        previous = None
        while True:
            task = _tasks.get(task_id)
            if not task:
                break
            payload = task.to_dict()
            if payload != previous:
                yield {"event": "update", "data": _json(payload)}
                previous = payload
            if task.status in {"done", "error"}:
                break
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/api/tasks/{task_id}/download/{fmt}")
def api_download(task_id: str, fmt: str):
    task = _get_task(task_id)
    if fmt not in task.output_files:
        raise HTTPException(404, "文件不存在")
    path = task.output_files[fmt]
    if not os.path.isfile(path):
        raise HTTPException(404, "文件已删除")
    return FileResponse(
        path,
        filename=_download_filename(task, path),
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )


def _download_filename(task: TaskInfo, path: str) -> str:
    """Name new and historical downloads from the title, keeping stored files intact."""
    title = task.requirement_title.strip()
    if is_local_path_reference(title) or title.lower().startswith(("http://", "https://")):
        title = ""
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]+', "_", title)
    title = re.sub(r"\s+", " ", title).strip(" ._")
    # Leave room for the suffix on filesystems with a 255-byte filename limit.
    title = title.encode("utf-8")[:200].decode("utf-8", errors="ignore").rstrip(" ._")
    title = title or "未命名需求"
    return f"{title}_测试用例{Path(path).suffix}"


def _run_task(task_id: str, req: GenRequest):
    task = _get_task(task_id)
    with _pipeline_lock:
        task.status = "running"
        task.stage = "读取需求链接" if req.source_mode == "link" else "准备生成"
        task.progress = 5
        task.stage_key = "parse"
        _persist_task(task)

        pipeline = Pipeline()
        listener = _WebListener(task)
        registry.register_listener(listener)

        try:
            result = pipeline.run(
                req.source,
                source_mode=req.source_mode,
                section=req.section,
                project=req.project,
                branch=req.branch,
                formats=req.formats,
                output_path=req.output_path,
                creator=req.creator,
                extra_prompt=req.extra_prompt,
                case_scope=req.case_scope,
                skip_code=req.skip_code,
                task_name=_source_preview(req.source, 60),
                progress_callback=listener.on_code_progress,
                repository_callback=listener.on_repository,
            )
            task.requirement_title = result.requirement.title if result.requirement else ""
            if result.requirement:
                task.requirement_source = _requirement_source_summary(result.requirement)
            task.case_count = len(result.cases)
            task.cases = [case.to_dict() for case in result.cases]
            task.output_files = {_detect_format(path): path for path in result.output_files}
            task.stats = result.stats
            task.timings = result.timings
            if result.code_context:
                task.repository = result.code_context.raw.get("repository", task.repository)
                task.routing = result.code_context.raw.get("routing", task.routing)
            task.status = "done"
            task.progress = 100
            task.stage = "生成完成"
            task.stage_key = "complete"
        except Exception as exc:
            task.status = "error"
            task.stage = "生成失败"
            task.error = str(exc)
        finally:
            task.finished_at = datetime.now().isoformat()
            if listener in registry.listeners:
                registry.listeners.remove(listener)
            _persist_task(task)


class _WebListener:
    """捕获管道阶段事件并更新任务状态。"""

    STAGE_MAP = {
        "parse": ("解析需求", 15),
        "analyze": ("分析代码", 25),
        "generate": ("Codex 生成用例", 68),
        "export": ("导出文件", 92),
    }

    def __init__(self, task: TaskInfo):
        self.task = task

    def on_stage_start(self, stage: str, **context):
        label, progress = self.STAGE_MAP.get(stage, (stage, self.task.progress))
        if stage == "parse" and self.task.source_mode == "link":
            label = "读取需求链接"
        self.task.stage = label
        self.task.stage_key = stage
        self.task.progress = progress
        _persist_task(self.task)

    def on_stage_end(self, stage: str, **context):
        if context.get("skipped"):
            if stage not in self.task.skipped_stages:
                self.task.skipped_stages.append(stage)
        elif context.get("success") and stage not in self.task.completed_stages:
            self.task.completed_stages.append(stage)
        requirement = context.get("requirement")
        if stage == "parse" and requirement:
            self.task.requirement_title = requirement.title
            self.task.requirement_source = _requirement_source_summary(requirement)
        _persist_task(self.task)

    def on_error(self, stage: str, error: Exception, **context):
        self.task.error = str(error)

    def on_code_progress(self, label: str, progress: int):
        self.task.stage = label
        self.task.stage_key = "analyze"
        self.task.progress = progress
        _persist_task(self.task)

    def on_repository(self, repository: dict, routing: dict):
        self.task.repository = dict(repository)
        self.task.routing = dict(routing)
        _persist_task(self.task)


def _get_task(task_id: str) -> TaskInfo:
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


def _checkpoint_path(task_id: str) -> Path:
    return CHECKPOINT_DIR / f"{task_id}.json"


def _persist_task(task: TaskInfo):
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_path(task.id)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(_json(task.to_dict()), encoding="utf-8")
    os.replace(temp_path, path)


def _load_checkpoints():
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    valid_fields = {item.name for item in fields(TaskInfo)}
    for path in CHECKPOINT_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            task = TaskInfo(**{key: value for key, value in payload.items() if key in valid_fields})
            if _repair_legacy_path_title(task):
                backup = path.with_suffix(".before-title-repair.bak")
                if not backup.exists():
                    shutil.copy2(path, backup)
                _persist_task(task)
            if task.status in {"pending", "running"}:
                task.status = "error"
                task.stage = "任务已中断"
                task.error = "本地服务曾在任务执行期间停止，请重新提交该任务。"
                task.finished_at = datetime.now().isoformat()
                _persist_task(task)
            _tasks[task.id] = task
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue


def _repair_legacy_path_title(task: TaskInfo) -> bool:
    """Repair mislabeled history without claiming the old cases used file content."""
    if task.source_mode != "path" or not is_local_path_reference(task.requirement_title):
        return False
    try:
        requirement = FileSource().parse(task.source)
        task.requirement_title = requirement.title
        task.requirement_source["title_recovered_from"] = requirement.source_ref
    except (OSError, ValueError):
        task.requirement_title = "本地需求（标题待确认）"
    if task.requirement_source.get("type") == "text":
        task.warning = "原任务误将文件地址当作正文，未读取完整需求文件。标题已修正，原用例仅供参考，请重新生成。"
        task.requirement_source["needs_regeneration"] = True
    return True


def _source_preview(source: str, limit: int = 96) -> str:
    normalized = " ".join(source.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "…"


def _requirement_source_summary(requirement) -> dict[str, Any]:
    extras = requirement.extras or {}
    return {
        "type": requirement.source_type,
        "ref": requirement.source_ref,
        "item_id": extras.get("item_id", ""),
        "task_code": extras.get("task_code", ""),
        "project_name": extras.get("project_name", ""),
        "status": extras.get("status", ""),
        "image_count": len(extras.get("image_urls", [])),
        "attachment_count": len(extras.get("attachments", [])),
    }


def _detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    mapping = {"xlsx": "excel", "xmind": "xmind", "md": "markdown", "json": "json"}
    return mapping.get(ext, ext)


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
