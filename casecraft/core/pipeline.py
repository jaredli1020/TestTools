"""管道编排 - 串联 Source -> Analyzer -> Generator -> Exporter

Pipeline 提供默认编排，业务可继承或组合自定义流程。所有阶段的错误、
进度都通过 StageListener / Notifier 广播。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

from .models import Requirement, CodeContext, TestCase
from .registry import Registry, registry as default_registry
from .config import Config, get_config


@dataclass
class PipelineResult:
    requirement: Requirement | None = None
    code_context: CodeContext | None = None
    cases: list[TestCase] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class Pipeline:
    """用例生成管道"""

    def __init__(self, registry_: Registry | None = None, config: Config | None = None):
        self.registry = registry_ or default_registry
        self.config = config or get_config()

    # ---------- 阶段事件 ----------

    def _emit_stage_start(self, stage: str, **ctx):
        for lis in self.registry.listeners:
            try:
                lis.on_stage_start(stage, **ctx)
            except Exception:
                pass
        for n in self.registry.notifiers:
            try:
                n.on_stage(ctx.get("task_name", ""), stage, **ctx)
            except Exception:
                pass

    def _emit_stage_end(self, stage: str, **ctx):
        for lis in self.registry.listeners:
            try:
                lis.on_stage_end(stage, **ctx)
            except Exception:
                pass

    def _emit_error(self, stage: str, err: Exception, task_name: str = ""):
        for lis in self.registry.listeners:
            try:
                lis.on_error(stage, err)
            except Exception:
                pass
        for n in self.registry.notifiers:
            try:
                n.on_error(task_name, stage, str(err))
            except Exception:
                pass

    # ---------- 管道阶段 ----------

    def parse_requirement(self, source: str, section: str | None = None, **kwargs) -> Requirement:
        mode = kwargs.pop("source_mode", None)
        if mode:
            source_name = {"path": "file", "text": "text", "link": "mongoso_share"}.get(mode)
            source_impl = next((item for item in self.registry.sources if item.name == source_name), None)
            if not source_impl:
                raise ValueError(f"未注册需求输入类型: {mode}")
        else:
            source_impl = self.registry.find_source(source)
        t0 = time.time()
        self._emit_stage_start("parse", source=source)
        req = None
        try:
            req = source_impl.parse(source, section=section, **kwargs)
        finally:
            self._emit_stage_end("parse", elapsed=time.time() - t0, success=req is not None, requirement=req)
        return req

    def analyze_code(self, requirement: Requirement, project_key: str | None = None,
                     branch: str | None = None, **kwargs) -> CodeContext:
        if not project_key:
            return CodeContext()

        project = self.config.projects.get(project_key)
        if not project:
            return CodeContext()

        project_with_key = {**project, "key": project_key}
        analyzer = self.registry.find_analyzer(project_with_key)
        if not analyzer:
            return CodeContext(project_key=project_key, project_type=project.get("type", ""))

        t0 = time.time()
        self._emit_stage_start("analyze", project=project_key, branch=branch)
        succeeded = False
        try:
            ctx = analyzer.analyze(requirement, project_with_key, branch=branch, **kwargs)
            succeeded = True
        except Exception as e:
            self._emit_error("analyze", e)
            if project.get("strict", False):
                raise
            ctx = CodeContext(project_key=project_key, project_type=project.get("type", ""))
        finally:
            self._emit_stage_end("analyze", elapsed=time.time() - t0, success=succeeded)
        return ctx

    def generate(self, requirement: Requirement, code_context: CodeContext | None = None,
                 generator_name: str | None = None, extra_prompt: str = "", **kwargs) -> list[TestCase]:
        gen = self.registry.get_generator(generator_name)
        t0 = time.time()
        self._emit_stage_start("generate", generator=gen.name)
        succeeded = False
        try:
            cases = gen.generate(requirement, code_context, extra_prompt=extra_prompt, **kwargs)
            succeeded = True
        finally:
            self._emit_stage_end("generate", elapsed=time.time() - t0, success=succeeded)
        return cases

    def export(self, cases: list[TestCase], formats: list[str] | str,
               output_path: str | None = None, **kwargs) -> list[str]:
        if isinstance(formats, str):
            formats = [formats]
        if "all" in formats:
            formats = self.registry.list_exporters()

        t0 = time.time()
        self._emit_stage_start("export", formats=formats)
        paths: list[str] = []
        succeeded = False
        try:
            for fmt in formats:
                exporter = self.registry.get_exporter(fmt)
                # 只有单一 format 时才使用 output_path，多 format 用默认命名
                path = exporter.export(
                    cases,
                    output_path if len(formats) == 1 else None,
                    **kwargs,
                )
                paths.append(os.path.abspath(path))
            succeeded = True
        finally:
            self._emit_stage_end("export", elapsed=time.time() - t0, success=succeeded)
        return paths

    # ---------- 一站式调用 ----------

    def run(self, source: str, *, section: str | None = None,
            project: str | None = None, branch: str | None = None,
            generator: str | None = None, extra_prompt: str = "",
            formats: list[str] | str = "excel", output_path: str | None = None,
            task_name: str = "",
            skip_code: bool = False,
            source_mode: str | None = None,
            **kwargs) -> PipelineResult:
        """执行完整管道"""
        result = PipelineResult()
        task_label = task_name or source[:60]

        for n in self.registry.notifiers:
            try:
                n.on_start(task_label)
            except Exception:
                pass

        monitor = _HeartbeatMonitor(self.registry, task_label,
                                    self.config.notify.heartbeat_interval)
        monitor.start()

        overall_t0 = time.time()
        try:
            # 1. 解析需求
            stage_t0 = time.time()
            monitor.update_stage("解析需求")
            req = self.parse_requirement(source, section=section, source_mode=source_mode)
            result.requirement = req
            result.timings["parse"] = round(time.time() - stage_t0, 2)

            # 2. 代码分析（可选）
            if not skip_code and project:
                stage_t0 = time.time()
                monitor.update_stage("代码分析")
                ctx = self.analyze_code(req, project_key=project, branch=branch, **kwargs)
                result.code_context = ctx
                result.timings["analyze"] = round(time.time() - stage_t0, 2)
            else:
                result.code_context = CodeContext()
                self._emit_stage_end("analyze", success=True, skipped=True, elapsed=0)

            # 3. 生成用例
            stage_t0 = time.time()
            monitor.update_stage("AI 生成用例")
            cases = self.generate(
                req,
                result.code_context,
                generator_name=generator,
                extra_prompt=extra_prompt,
                **kwargs,
            )
            result.cases = cases
            result.timings["generate"] = round(time.time() - stage_t0, 2)

            # 4. 导出
            if cases:
                stage_t0 = time.time()
                monitor.update_stage("导出文件")
                result.output_files = self.export(cases, formats, output_path, **kwargs)
                result.timings["export"] = round(time.time() - stage_t0, 2)

            # 5. 统计
            result.stats = _compute_stats(cases)

        except Exception as e:
            result.error = str(e)
            self._emit_error("pipeline", e, task_name=task_label)
            for n in self.registry.notifiers:
                try:
                    n.on_error(task_label, monitor.stage, str(e))
                except Exception:
                    pass
            raise
        else:
            for n in self.registry.notifiers:
                try:
                    n.on_finish(task_label, len(result.cases), result.output_files)
                except Exception:
                    pass
        finally:
            monitor.stop()
            result.timings["total"] = round(time.time() - overall_t0, 2)

        return result


def _compute_stats(cases: list[TestCase]) -> dict:
    priorities: dict[str, int] = {}
    tags: dict[str, int] = {}
    sources: dict[str, int] = {}
    for c in cases:
        priorities[c.get("优先级", "未知")] = priorities.get(c.get("优先级", "未知"), 0) + 1
        tags[c.get("标签", "未知")] = tags.get(c.get("标签", "未知"), 0) + 1
        sources[c.get("用例来源", "未知")] = sources.get(c.get("用例来源", "未知"), 0) + 1
    return {"priorities": priorities, "tags": tags, "sources": sources, "total": len(cases)}


class _HeartbeatMonitor:
    """心跳监测器 - 后台线程定期通知 Notifier 任务仍在运行"""

    def __init__(self, registry_: Registry, task_name: str, interval: int):
        self.registry = registry_
        self.task_name = task_name
        self.interval = max(10, int(interval))
        self.stage = "init"
        self.start_time = time.time()
        self.last_update = time.time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if not self.registry.notifiers:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def update_stage(self, stage: str):
        self.stage = stage
        self.last_update = time.time()

    def stop(self):
        self._stop.set()

    def _loop(self):
        heartbeat = 0
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                break
            heartbeat += 1
            if heartbeat % 2 != 0:
                continue
            for n in self.registry.notifiers:
                try:
                    n.on_heartbeat(
                        self.task_name, self.stage,
                        elapsed=time.time() - self.start_time,
                        idle=time.time() - self.last_update,
                    )
                except Exception:
                    pass
