"""本地文件需求源 - 读取 .md / .txt / .json"""

import os
import json

from casecraft.core import RequirementSource, Requirement


class FileSource(RequirementSource):
    name = "file"
    SUPPORTED_EXTS = {".md", ".txt", ".json", ".markdown", ".rst"}

    def match(self, source: str) -> bool:
        if not isinstance(source, str):
            return False
        if not os.path.isfile(source):
            return False
        ext = os.path.splitext(source)[1].lower()
        return ext in self.SUPPORTED_EXTS

    def parse(self, source: str, *, section: str | None = None, **kwargs) -> Requirement:
        with open(source, "r", encoding="utf-8") as f:
            raw = f.read()

        ext = os.path.splitext(source)[1].lower()
        if ext == ".json":
            try:
                data = json.loads(raw)
                content = data.get("content") or data.get("description") or json.dumps(data, ensure_ascii=False, indent=2)
                title = data.get("title") or os.path.basename(source)
            except json.JSONDecodeError:
                content = raw
                title = os.path.basename(source)
        else:
            content = raw
            # 从 markdown 首行 h1 提取标题
            title = os.path.basename(source)
            for line in raw.splitlines()[:5]:
                stripped = line.strip()
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    break

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
