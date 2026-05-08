"""GitLab API 客户端 - 远程读取代码仓库

业务分析器可用此客户端从 GitLab 拉取文件，而无需本地 clone。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests


class GitLabClient:
    """GitLab API 封装"""

    def __init__(self, base_url: str, token: str, *, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ---------- helpers ----------

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self.token}

    def _encode_path(self, path: str) -> str:
        return requests.utils.quote(path, safe="")

    def _get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        kwargs["proxies"] = {"http": None, "https": None}
        resp = requests.get(url, headers=self._headers(), **kwargs)
        resp.raise_for_status()
        return resp

    # ---------- public API ----------

    def get_project_id(self, project_path: str) -> int:
        resp = self._get(f"{self.base_url}/api/v4/projects/{self._encode_path(project_path)}")
        return resp.json()["id"]

    def list_branches(self, project_path: str, search: str = "", per_page: int = 100) -> list[dict]:
        project_id = self.get_project_id(project_path)
        all_branches = []
        page = 1
        while True:
            params = {"per_page": per_page, "page": page}
            if search:
                params["search"] = search
            resp = self._get(
                f"{self.base_url}/api/v4/projects/{project_id}/repository/branches",
                params=params,
            )
            branches = resp.json()
            if not branches:
                break
            all_branches.extend(branches)
            if len(branches) < per_page:
                break
            page += 1

        now = datetime.now(timezone.utc)
        result = []
        for b in all_branches:
            committed = b["commit"]["committed_date"]
            try:
                dt = datetime.fromisoformat(committed.replace("Z", "+00:00"))
                days_ago = (now - dt).days
            except Exception:
                days_ago = 999
            if days_ago <= 14:
                activity = "active"
            elif days_ago <= 90:
                activity = "recent"
            else:
                activity = "stale"
            result.append({
                "name": b["name"],
                "commit_id": b["commit"]["short_id"],
                "commit_title": b["commit"]["title"][:80],
                "updated_at": committed,
                "default": b.get("default", False),
                "activity": activity,
                "days_ago": days_ago,
            })

        order = {"active": 0, "recent": 1, "stale": 2}
        result.sort(key=lambda x: (not x["default"], order.get(x["activity"], 9), x["days_ago"]))
        return result

    def list_tree(self, project_path: str, ref: str = "master",
                  path: str = "", recursive: bool = False) -> list[dict]:
        project_id = self.get_project_id(project_path)
        all_items = []
        page = 1
        while True:
            params = {"ref": ref, "per_page": 100, "page": page}
            if path:
                params["path"] = path
            if recursive:
                params["recursive"] = "true"
            resp = self._get(
                f"{self.base_url}/api/v4/projects/{project_id}/repository/tree",
                params=params,
            )
            items = resp.json()
            if not items:
                break
            all_items.extend(items)
            if len(items) < 100:
                break
            page += 1
        return all_items

    def get_file_content(self, project_path: str, file_path: str, ref: str = "master") -> str:
        project_id = self.get_project_id(project_path)
        encoded = self._encode_path(file_path)
        resp = self._get(
            f"{self.base_url}/api/v4/projects/{project_id}/repository/files/{encoded}/raw",
            params={"ref": ref},
        )
        return resp.text

    def get_files_by_paths(self, project_path: str, file_paths: list[str],
                           ref: str = "master", max_workers: int = 8) -> dict[str, str]:
        result: dict[str, str] = {}

        def fetch_one(fp: str):
            try:
                return fp, self.get_file_content(project_path, fp, ref)
            except Exception:
                return fp, None

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(fetch_one, fp): fp for fp in file_paths}
            for fut in as_completed(futures):
                fp, content = fut.result()
                if content is not None:
                    result[fp] = content
        return result
