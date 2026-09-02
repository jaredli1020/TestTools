"""Mongoso MAX 分享需求源。

分享页本身是单页应用；真正的需求数据来自公开的只读分享接口。
该实现只接受 ``max.mongoso.com/share`` 链接，避免把需求源变成任意 URL
抓取器，并将富文本正文转换为适合 Codex 消费的纯文本。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from casecraft.core import Requirement, RequirementSource


class MongosoShareSource(RequirementSource):
    """读取 ``https://max.mongoso.com/share?itemid=...`` 分享需求。"""

    name = "mongoso_share"
    HOST = "max.mongoso.com"
    SHARE_PATH = "/share"
    DETAIL_API = "https://max.mongoso.com/max/share/queryTaskDetail"
    ITEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,80}$")
    IMAGE_HOSTS = {"maxfile.mongoso.com"}
    MAX_HTML_CHARS = 2_000_000
    MAX_IMAGES = 20
    MAX_IMAGE_BYTES = 8 * 1024 * 1024

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        download_images: bool = True,
        image_cache_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.download_images = download_images
        self.image_cache_dir = Path(
            image_cache_dir
            or Path(tempfile.gettempdir()) / "casecraft-requirements" / "mongoso"
        )

    @classmethod
    def extract_item_id(cls, source: str) -> str | None:
        """严格提取分享 itemid；无效或非白名单链接返回 ``None``。"""
        if not isinstance(source, str):
            return None
        try:
            parsed = urlparse(source.strip())
        except ValueError:
            return None
        if parsed.scheme.lower() != "https":
            return None
        if parsed.netloc.lower() != cls.HOST:
            return None
        if parsed.path.rstrip("/") != cls.SHARE_PATH:
            return None
        item_ids = parse_qs(parsed.query).get("itemid", [])
        item_id = item_ids[0].strip() if item_ids else ""
        if not cls.ITEM_ID_PATTERN.fullmatch(item_id):
            return None
        return item_id

    def match(self, source: str) -> bool:
        return self.extract_item_id(source) is not None

    def parse(
        self,
        source: str,
        *,
        section: str | None = None,
        **kwargs: Any,
    ) -> Requirement:
        item_id = self.extract_item_id(source)
        if not item_id:
            raise ValueError(
                "请输入有效的 Mongoso 需求分享链接，例如 "
                "https://max.mongoso.com/share?itemid=T749nod"
            )

        canonical_url = f"https://{self.HOST}{self.SHARE_PATH}?itemid={item_id}"
        data = self._fetch_detail(item_id, canonical_url)
        raw_html = str(data.get("taskDesc") or data.get("itemContent") or "")
        if len(raw_html) > self.MAX_HTML_CHARS:
            raise ValueError("需求正文过大，暂不支持读取超过 2,000,000 字符的文档")

        parser = _MongosoHtmlExtractor()
        parser.feed(raw_html)
        parser.close()
        content = parser.get_text()
        if not content:
            raise ValueError("需求分享链接中没有可读取的正文内容")

        image_urls = _deduplicate(parser.images)[: self.MAX_IMAGES]
        cached_images = (
            self._cache_images(item_id, image_urls, canonical_url)
            if self.download_images
            else []
        )
        attachments = _normalize_attachments(data.get("fileList"))
        associations = _normalize_associations(data.get("associationTaskList"))

        task_code = str(data.get("taskCode") or "").strip()
        title = str(data.get("taskTitle") or "").strip()
        if not title:
            title = f"Mongoso 需求 {task_code or item_id}"

        extras = {
            "provider": "mongoso_max",
            "item_id": item_id,
            "task_id": str(data.get("taskId") or ""),
            "task_code": task_code,
            "project_name": str(data.get("projectName") or ""),
            "task_set_name": str(data.get("taskSetName") or ""),
            "status": str(data.get("taskStatusName") or ""),
            "priority": str(data.get("priority") or ""),
            "assignee": str(data.get("directorName") or ""),
            "creator": str(data.get("creator") or ""),
            "created_at": str(data.get("createdDt") or ""),
            "updated_by": str(data.get("updator") or ""),
            "updated_at": str(data.get("updatedDt") or ""),
            "image_urls": image_urls,
            "cached_images": cached_images,
            "attachments": attachments,
            "associations": associations,
        }
        return Requirement(
            title=title,
            content=content,
            source_type=self.name,
            source_ref=canonical_url,
            images=cached_images or image_urls,
            extras=extras,
        )

    def _fetch_detail(self, item_id: str, source_url: str) -> dict[str, Any]:
        try:
            response = self.session.post(
                self.DETAIL_API,
                params={"token": "undefined"},
                json={"taskId": item_id, "loading": True},
                headers={
                    "Accept": "application/json",
                    "Origin": f"https://{self.HOST}",
                    "Referer": source_url,
                    "User-Agent": "CaseCraft/0.2 (+local requirement reader)",
                },
                timeout=(8, 35),
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise ValueError("读取 Mongoso 需求超时，请稍后重试") from exc
        except (requests.RequestException, ValueError) as exc:
            raise ValueError(f"无法读取 Mongoso 需求分享链接: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Mongoso 分享接口返回了无法识别的数据")
        data = payload.get("data")
        if payload.get("code") != "000000" or not isinstance(data, dict):
            detail = payload.get("msg") or "链接无效、已失效或没有读取权限"
            raise ValueError(f"无法读取 Mongoso 需求: {detail}")
        return data

    def _cache_images(
        self,
        item_id: str,
        image_urls: list[str],
        source_url: str,
    ) -> list[str]:
        target_dir = self.image_cache_dir / item_id
        cached: list[str] = []
        for image_url in image_urls:
            parsed = urlparse(image_url)
            if parsed.scheme.lower() != "https" or parsed.netloc.lower() not in self.IMAGE_HOSTS:
                continue
            suffix = Path(parsed.path).suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                suffix = ".img"
            filename = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:20] + suffix
            target = target_dir / filename
            if target.is_file() and 0 < target.stat().st_size <= self.MAX_IMAGE_BYTES:
                cached.append(str(target.resolve()))
                continue

            try:
                response = self.session.get(
                    image_url,
                    headers={"Referer": source_url, "User-Agent": "CaseCraft/0.2"},
                    timeout=(8, 25),
                    stream=True,
                )
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and not content_type.startswith("image/"):
                    response.close()
                    continue
                target_dir.mkdir(parents=True, exist_ok=True)
                total = 0
                with target.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > self.MAX_IMAGE_BYTES:
                            raise ValueError("image too large")
                        output.write(chunk)
                response.close()
                if total:
                    cached.append(str(target.resolve()))
            except (OSError, ValueError, requests.RequestException):
                target.unlink(missing_ok=True)
                continue
        return cached


class _MongosoHtmlExtractor(HTMLParser):
    """将 Tiptap 富文本转换为保留结构的紧凑纯文本。"""

    BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "div", "figcaption",
        "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "main", "nav", "p", "section", "table", "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[str] = []
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = dict(attrs)
        if tag in self.BLOCK_TAGS or tag in {"ul", "ol"}:
            self._newline()
        elif tag == "br":
            self._newline()
        elif tag == "li":
            self._newline()
            self.parts.append("- ")
        elif tag in {"td", "th"}:
            if self.parts and not self.parts[-1].endswith(("\n", " | ")):
                self.parts.append(" | ")
        elif tag == "pre":
            self._newline()
            self._pre_depth += 1
        elif tag == "img":
            src = str(attributes.get("src") or "").strip()
            if src:
                self.images.append(src)
                self._newline()
                self.parts.append(f"[需求截图 {len(self.images)}]")
                self._newline()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
            self._newline()
        elif tag in self.BLOCK_TAGS or tag in {"li", "ul", "ol"}:
            self._newline()

    def handle_data(self, data: str) -> None:
        if not data:
            return
        text = data if self._pre_depth else re.sub(r"[\t\r\f\v ]+", " ", data)
        if not text.strip() and "\n" not in text:
            return
        self.parts.append(text)

    def _newline(self) -> None:
        if not self.parts or not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def get_text(self) -> str:
        raw = "".join(self.parts).replace("\xa0", " ")
        lines = [line.strip() for line in raw.splitlines()]
        compact: list[str] = []
        for line in lines:
            if not line:
                if compact and compact[-1] != "":
                    compact.append("")
                continue
            compact.append(line)
        return "\n".join(compact).strip()


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _normalize_attachments(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("fileName") or item.get("name") or item.get("title") or "附件"
        url = item.get("fileUrl") or item.get("url") or item.get("downloadUrl") or ""
        result.append({"name": str(name), "url": str(url)})
    return result


def _normalize_associations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        code = item.get("taskCode") or item.get("code") or ""
        title = item.get("taskTitle") or item.get("title") or ""
        result.append({"code": str(code), "title": str(title)})
    return result
