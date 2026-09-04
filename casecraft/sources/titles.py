"""Extract a local requirement title without model calls or external retrieval."""

from __future__ import annotations

import json
import re


_TITLE_KEYS = ("title", "需求标题", "需求名称", "标题", "taskTitle", "doc_title")
_TITLE_FIELD = re.compile(
    r"^(?:需求标题|需求名称|文档标题|文档名称|标题|title|taskTitle|doc_title)\s*[:：]\s*(.+)$",
    re.IGNORECASE,
)
_GENERIC_HEADINGS = {
    "需求", "需求文档", "产品需求文档", "需求说明", "需求说明书", "需求描述",
    "需求内容", "需求详情", "需求背景", "项目背景", "背景", "概述", "文档信息",
    "基本信息", "功能需求", "功能描述", "验收标准", "当前结果", "期待结果",
    "预期结果", "正文", "prd", "requirements",
}
_METADATA = re.compile(
    r"^(?:作者|创建人|负责人|日期|创建时间|更新时间|版本|需求编号|项目|所属项目|"
    r"author|date|version|status|tags)\s*[:：]", re.IGNORECASE
)


def is_local_path_reference(value: str) -> bool:
    value = value.strip().strip('"\'')
    return "\n" not in value and bool(re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?!/)|\.\.?[\\/])", value))


def _clean_title(value: str) -> str:
    value = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[*`]+", "", value)
    value = re.sub(r"\s+", " ", value).strip().strip('"\'')
    return value if len(value) <= 120 else value[:119].rstrip() + "…"


def _is_generic(value: str) -> bool:
    value = re.sub(r"^(?:\d+[.、)）]|[一二三四五六七八九十]+[、.])\s*", "", value)
    return value.strip(" :：").lower() in _GENERIC_HEADINGS


def extract_requirement_title(content: str, *, fallback: str = "未命名需求") -> str:
    """Prefer explicit document titles, then a useful first sentence.

    Titles inside fenced examples, comments or metadata are not requirements.
    The original requirement body is never modified by this helper.
    """
    text = content.lstrip("\ufeff").strip()
    if is_local_path_reference(text):
        return fallback
    if text.startswith(("{", "[")):
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            data = None
        if isinstance(data, dict):
            for key in _TITLE_KEYS:
                value = data.get(key)
                if isinstance(value, str) and value.strip() and not is_local_path_reference(value):
                    return _clean_title(value)
            body = data.get("content") or data.get("description")
            if isinstance(body, str):
                text = body
            else:
                return fallback
        elif data is not None:
            return fallback

    # Bound discovery to the document header, excluding fenced code examples.
    text = re.sub(r"<!--.*?-->", "", text[:65536], flags=re.DOTALL)
    lines: list[str] = []
    fence = ""
    frontmatter = False
    for index, raw_line in enumerate(text.splitlines()[:300]):
        line = raw_line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", line)
        if marker:
            delimiter = marker.group(1)
            if not fence:
                fence = delimiter
            elif delimiter[0] == fence[0] and len(delimiter) >= len(fence):
                fence = ""
            continue
        if fence:
            continue
        if line.startswith(".. "):
            continue
        if index == 0 and line == "---":
            frontmatter = True
            continue
        if frontmatter and line in {"---", "..."}:
            frontmatter = False
            continue
        candidate = _clean_title(re.sub(r"^#{1,6}\s+", "", line))
        field = _TITLE_FIELD.match(candidate)
        if field and not is_local_path_reference(field.group(1)):
            return _clean_title(field.group(1))
        if field:
            continue
        if not frontmatter and line:
            lines.append(line)

    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        heading = re.match(r"^(#{1,6})\s+(.+?)(?:\s+#+)?$", line)
        if heading:
            title = _clean_title(heading.group(2))
            if title and not _is_generic(title) and not is_local_path_reference(title):
                headings.append((len(heading.group(1)), title))
        # Markdown Setext and reStructuredText underlined document titles.
        elif index + 1 < len(lines) and re.fullmatch(r"([=\-~^])\1{2,}", lines[index + 1]):
            title = _clean_title(line)
            if title and not _is_generic(title) and not is_local_path_reference(title):
                headings.append((1, title))
        elif index == 0:
            # Pasted documents often keep the title as plain/bold text while
            # retaining Markdown subheadings below it. Keep the document title.
            title = _clean_title(line)
            if (
                title and len(title) <= 80 and not _is_generic(title)
                and not is_local_path_reference(title)
                and not _METADATA.match(title)
                and not re.search(r"[。！？；:：]|[.!?;](?=\s|$)", title)
                and not re.match(r"^(?:[-*+>]|\d+[.)、]|[|{\[])|https?://", title)
            ):
                headings.append((1, title))
    if headings:
        return min(headings, key=lambda item: item[0])[1]

    for line in lines:
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^(?:[-*+]\s+|\d+[.)、]\s*)", "", line)
        title = _clean_title(line)
        if not title or _is_generic(title) or _METADATA.match(title):
            continue
        if is_local_path_reference(title):
            continue
        if re.fullmatch(r"[-=*_~^:|\s]+", title) or title.startswith(("|", "http://", "https://")):
            continue
        title = re.split(r"[。！？；]|[.!?;](?=\s|$)", title, maxsplit=1)[0].strip()
        if title:
            return title
    return fallback
