"""本地文件需求源 - 读取 .md / .txt / .json"""

import os
import json
from pathlib import Path

from casecraft.core import RequirementSource, Requirement
from .titles import extract_requirement_title


class FileSource(RequirementSource):
    name = "file"
    SUPPORTED_EXTS = {".md", ".txt", ".json", ".markdown", ".rst"}

    def match(self, source: str) -> bool:
        if not isinstance(source, str):
            return False
        try:
            self.resolve_path(source)
        except (ValueError, OSError):
            return False
        return True

    @classmethod
    def resolve_path(cls, source: str) -> Path:
        """Resolve only an exact file or a unique supported-extension match."""
        path = Path(source.strip().strip('"\''))
        if path.is_dir():
            raise ValueError("请选择需求文件，不能使用文件夹路径。")
        if path.is_file():
            if path.suffix.lower() not in cls.SUPPORTED_EXTS:
                raise ValueError("不支持该文件类型，请使用 .md、.txt、.json、.markdown 或 .rst 文件。")
            return path.resolve()
        if not path.suffix:
            matches = [Path(str(path) + ext) for ext in sorted(cls.SUPPORTED_EXTS)]
            matches = [candidate for candidate in matches if candidate.is_file()]
            if len(matches) == 1:
                return matches[0].resolve()
            if len(matches) > 1:
                raise ValueError("找到多个同名需求文件，请填写包含扩展名的完整路径。")
        raise ValueError("需求文件不存在，请检查路径及扩展名（例如 .md）。不会将文件路径当作需求正文生成用例。")

    def parse(self, source: str, *, section: str | None = None, **kwargs) -> Requirement:
        source = str(self.resolve_path(source))
        with open(source, "r", encoding="utf-8-sig") as f:
            raw = f.read()

        title = kwargs.get("title") or extract_requirement_title(
            raw, fallback=os.path.splitext(os.path.basename(source))[0]
        )
        ext = os.path.splitext(source)[1].lower()
        if ext == ".json":
            try:
                data = json.loads(raw)
                content = (data.get("content") or data.get("description")) if isinstance(data, dict) else None
                if not isinstance(content, str) or not content:
                    content = json.dumps(data, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                content = raw
        else:
            content = raw

        # section 过滤（按 markdown 标题切片）
        if section:
            content = _extract_section(content, section) or content

        return Requirement(
            title=title,
            content=content,
            source_type="file",
            source_ref=os.path.abspath(source),
        )


def _extract_section(text: str, section: str) -> str:
    """从 markdown 文本中提取指定标题下的内容"""
    lines = text.splitlines()
    target = section.strip().lower()
    out: list[str] = []
    in_section = False
    section_level = 0

    for line in lines:
        stripped = line.strip()
        heading = _parse_heading(stripped)
        if heading:
            level, heading_text = heading
            if not in_section and heading_text.lower() == target:
                in_section = True
                section_level = level
                continue
            if in_section and level <= section_level:
                break
        if in_section:
            out.append(line)

    return "\n".join(out).strip()


def _parse_heading(line: str) -> tuple[int, str] | None:
    if not line.startswith("#"):
        return None
    i = 0
    while i < len(line) and line[i] == "#":
        i += 1
    if i == 0 or i > 6 or not line[i:i + 1] == " ":
        return None
    return i, line[i + 1:].strip()
