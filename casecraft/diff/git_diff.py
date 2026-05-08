"""基于 git 的 Diff 分析器 - 通用实现

提供：
- 变更文件列表（路径 + 增删行数）
- 按方法定位变更（需要项目特定的解析器，框架默认跳过）

业务可继承 GitDiffAnalyzer 覆盖 _extract_changed_methods、_find_affected_routes
实现语言特定的方法解析。
"""

from __future__ import annotations

import os
import re
import subprocess

from .base import DiffAnalyzer, DiffResult


class GitDiffAnalyzer(DiffAnalyzer):
    name = "git_diff"

    def __init__(self, file_extensions: tuple[str, ...] = (".php", ".go", ".py", ".java", ".ts", ".js")):
        self.file_extensions = file_extensions

    def analyze(self, project: dict, *, diff_ref: str = "HEAD~1", **kwargs) -> DiffResult:
        project_path = project.get("path", "")
        if not project_path or not os.path.isdir(project_path):
            return DiffResult(diff_ref=diff_ref, summary=f"项目路径不存在: {project_path}")

        changed_files = self._get_changed_files(project_path, diff_ref)
        changed_methods = []
        for finfo in changed_files:
            methods = self._extract_changed_methods(project_path, finfo["path"], diff_ref)
            for m in methods:
                changed_methods.append({"file": finfo["path"], "method": m})

        return DiffResult(
            diff_ref=diff_ref,
            changed_files=changed_files,
            changed_methods=changed_methods,
            affected_routes=self._find_affected_routes(project, changed_files, changed_methods),
            impact_chain=[],
        )

    # ---------- 子类可覆盖 ----------

    def _get_changed_files(self, project_path: str, diff_ref: str) -> list[dict]:
        try:
            result = subprocess.run(
                ["git", "diff", diff_ref, "--numstat"],
                cwd=project_path,
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
        except Exception:
            return []

        files = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            if not path.endswith(self.file_extensions):
                continue
            files.append({
                "path": path,
                "added": int(added) if added != "-" else 0,
                "deleted": int(deleted) if deleted != "-" else 0,
            })
        return files

    def _extract_changed_methods(self, project_path: str, file_path: str, diff_ref: str) -> list[str]:
        """默认按启发式识别变更的方法名 - 业务可重写为 AST 解析"""
        try:
            result = subprocess.run(
                ["git", "diff", diff_ref, "--", file_path],
                cwd=project_path,
                capture_output=True, text=True, timeout=10,
            )
            diff_text = result.stdout
        except Exception:
            return []

        # diff hunk header: @@ -a,b +c,d @@ function ...
        methods = re.findall(r"@@ [^@]+ @@\s+(.+)", diff_text)
        cleaned = []
        for m in methods:
            # 取函数名（PHP/Go/Python 通用启发式）
            match = re.search(r"(?:function|func|def)\s+(\w+)", m)
            if match:
                cleaned.append(match.group(1))
            elif m.strip():
                cleaned.append(m.strip()[:80])
        return list(dict.fromkeys(cleaned))

    def _find_affected_routes(self, project: dict, files: list[dict], methods: list[dict]) -> list[dict]:
        """默认不实现，业务可按需覆盖（扫描路由配置关联变更方法）"""
        return []
