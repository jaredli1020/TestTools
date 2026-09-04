"""Opt-in live CLI check; uses a synthetic requirement, never production history.

Run from the repository: python -X utf8 tests/smoke_codex_background.py
Requires an already signed-in CLI; consumes a small amount of model usage.
"""

import base64
import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casecraft.core import Requirement
from casecraft.generators.llm import CodexCaseGenerator


def main():
    logging.basicConfig(level=logging.INFO)
    generator = CodexCaseGenerator()
    settings = generator._settings()
    if settings["provider"] != "codex_cli":
        raise SystemExit("This smoke check requires llm.provider=codex_cli")

    with tempfile.TemporaryDirectory(prefix="casecraft-background-smoke-") as folder:
        # A synthetic one-pixel PNG verifies attachment transport, not UI analysis.
        image = Path(folder) / "fixture.png"
        image.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWZ8AAAAASUVORK5CYII="
        ))
        cases = generator.generate(
            Requirement(
                title="CaseCraft 后台隔离冒烟测试",
                content="测试规则：用户名为空时，保存失败并提示‘请输入用户名’。仅输出这一条测试用例。",
                source_ref="https://example.invalid/requirement/already-read",
                images=[str(image)],
            ),
            extra_prompt="只生成 1 条用例；附图是传输测试像素，不含额外需求。不要访问来源或调用任何工具。",
        )
    assert len(cases) == 1, f"Expected one test case, received {len(cases)}"
    print(json.dumps({
        "status": "ok", "case_count": len(cases),
        "model": settings["model"], "reasoning_effort": settings["reasoning_effort"],
        "tool_events": 0, "production_tasks_created": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
