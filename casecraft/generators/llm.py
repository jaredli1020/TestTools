"""OpenAI/Codex 测试用例生成器。

通过 OpenAI Responses API 调用 Codex 同代模型，并使用 Structured Outputs
约束返回结构。模块保留 ``LLMCaseGenerator`` 兼容类，避免已有扩展代码失效。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from casecraft.core import CaseGenerator, Requirement, CodeContext, TestCase
from casecraft.core import get_config


DEFAULT_SYSTEM_PROMPT = """你是 Codex，也是一名资深高级测试工程师。请根据需求文档和代码逻辑生成高质量、可执行的测试用例。

核心约束：
1. 如果同时提供需求文档和代码分析，结果必须同时包含“需求文档”来源和“代码分析-xxx”来源的用例。
2. 不生成语义重复或仅测试数据不同的用例；本质相同的场景合并为一条。
3. 严格遵守调用方提供的 JSON Schema，不输出解释文字或 Markdown。

生成策略：

第一阶段：基于需求文档生成
- 从用户视角逐句分析需求，每个功能点、业务规则、交互逻辑都应有对应用例。
- 对比“现状”与“期望”，验证新旧逻辑差异。
- 覆盖需求中隐含的边界条件和异常场景。
- 用例来源标注为“需求文档”。

第二阶段：基于代码分析补充（提供代码上下文时执行）
- 条件分支：来源标注“代码分析-条件分支”。
- 异常处理：来源标注“代码分析-异常处理”。
- 参数校验：来源标注“代码分析-验证规则”。
- 接口权限：来源标注“代码分析-权限配置”。
- 状态判断：来源标注“代码分析-状态流转”。
- 数据约束：来源标注“代码分析-数据约束”。
- 优先补充 P0/P1 高价值测试点，不穷举低价值分支。

系统性检查输入、业务规则、权限、数据状态、状态流转和依赖异常。优先级规则：
- P0：核心主流程、权限控制、数据安全。
- P1：重要业务分支、常见异常。
- P2：边界值、非核心功能。
- P3：低频场景、UI 或提示类。

质量规则：一条用例只验证一个测试点；步骤可执行、无歧义；预期结果具体可验证；测试数据尽量使用真实格式；删除线文本视为废弃需求。
"""


CASE_FIELDS = [
    "模块",
    "用例标题",
    "优先级",
    "用例类型",
    "前置条件",
    "操作步骤",
    "预期结果",
    "测试数据",
    "关联接口",
    "标签",
    "用例来源",
    "备注",
]

TEST_CASES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {field: {"type": "string"} for field in CASE_FIELDS},
                "required": CASE_FIELDS,
                "additionalProperties": False,
            },
        }
    },
    "required": ["cases"],
    "additionalProperties": False,
}


class CodexCaseGenerator(CaseGenerator):
    """通过 Responses API 或本地 Codex CLI 生成测试用例。"""

    name = "codex"

    def __init__(
        self,
        system_prompt: str | None = None,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ):
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self._model = model
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort

    def _settings(self) -> dict[str, Any]:
        cfg = get_config().llm
        provider = (cfg.provider or "openai").lower().replace("-", "_")
        if provider not in {"openai", "codex", "codex_cli"}:
            raise ValueError(
                "CodexCaseGenerator 需要 llm.provider 为 openai、codex "
                f"或 codex_cli，当前为 {cfg.provider!r}"
            )

        return {
            "provider": provider,
            "api_key": cfg.api_key or os.getenv("OPENAI_API_KEY") or "",
            "base_url": cfg.base_url or os.getenv("OPENAI_BASE_URL") or "",
            "model": self._model or cfg.model or "gpt-5.6",
            "max_tokens": self._max_tokens or cfg.max_tokens,
            "reasoning_effort": self._reasoning_effort or cfg.reasoning_effort,
            "cli_path": cfg.cli_path or "codex",
            "timeout": max(1, int(cfg.timeout)),
        }

    def generate(
        self,
        requirement: Requirement,
        code_context: CodeContext | None = None,
        *,
        extra_prompt: str = "",
        **kwargs,
    ) -> list[TestCase]:
        settings = self._settings()
        user_message = _build_user_message(requirement, code_context, extra_prompt)
        if settings["provider"] == "codex_cli":
            text = self._generate_via_cli(
                settings,
                user_message,
                image_paths=_local_image_paths(requirement.images),
            )
        else:
            text = self._generate_via_api(settings, user_message)

        raw_cases = _parse_case_payload(text)
        return [TestCase.from_dict(case) for case in raw_cases]

    def _generate_via_api(self, settings: dict[str, Any], user_message: str) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("需要安装 OpenAI SDK: pip install openai") from exc

        if not settings["api_key"]:
            raise ValueError(
                "未找到 OpenAI API Key，请配置 config.yaml 的 llm.api_key "
                "或环境变量 OPENAI_API_KEY；也可将 llm.provider 设为 codex_cli "
                "以复用 Codex CLI 登录"
            )

        client_kwargs: dict[str, Any] = {"api_key": settings["api_key"]}
        if settings["base_url"]:
            client_kwargs["base_url"] = settings["base_url"]
        client = OpenAI(**client_kwargs)

        request: dict[str, Any] = {
            "model": settings["model"],
            "instructions": self.system_prompt,
            "input": user_message,
            "max_output_tokens": settings["max_tokens"],
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "casecraft_test_cases",
                    "strict": True,
                    "schema": TEST_CASES_SCHEMA,
                }
            },
        }
        if settings["reasoning_effort"]:
            request["reasoning"] = {"effort": settings["reasoning_effort"]}

        try:
            response = client.responses.create(**request)
        except Exception as exc:
            raise ValueError(f"OpenAI Responses API 调用失败: {exc}") from exc

        text = getattr(response, "output_text", "") or ""
        if not text:
            status = getattr(response, "status", "unknown")
            details = getattr(response, "incomplete_details", None)
            suffix = f"，详情: {details}" if details else ""
            raise ValueError(f"OpenAI API 未返回文本，响应状态: {status}{suffix}")
        return text

    def _generate_via_cli(
        self,
        settings: dict[str, Any],
        user_message: str,
        *,
        image_paths: list[str] | None = None,
    ) -> str:
        prompt = f"{self.system_prompt}\n\n{user_message}"
        with tempfile.TemporaryDirectory(prefix="casecraft-codex-") as temp_dir:
            temp_path = Path(temp_dir)
            schema_path = temp_path / "test-cases.schema.json"
            output_path = temp_path / "test-cases.json"
            schema_path.write_text(
                json.dumps(TEST_CASES_SCHEMA, ensure_ascii=False),
                encoding="utf-8",
            )

            executable = shutil.which(settings["cli_path"]) or settings["cli_path"]
            command = [
                executable,
                "exec",
                "--config",
                f'model_reasoning_effort={settings["reasoning_effort"]}',
                "--ephemeral",
                "--sandbox",
                "read-only",
                *(["--image", *image_paths] if image_paths else []),
                "--model",
                settings["model"],
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ]
            if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
                command = [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/s",
                    "/c",
                    subprocess.list2cmdline(command),
                ]
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=settings["timeout"],
                    check=False,
                    creationflags=creation_flags,
                )
            except FileNotFoundError as exc:
                raise ValueError(
                    f"未找到 Codex CLI: {settings['cli_path']!r}；请安装 Codex CLI "
                    "或在 config.yaml 配置 llm.cli_path"
                ) from exc
            except PermissionError as exc:
                raise ValueError(
                    "Codex CLI 无法执行；请安装可由当前用户运行的独立 Codex CLI，"
                    "或改用 llm.provider=openai"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise ValueError(
                    f"Codex CLI 生成超时（{settings['timeout']} 秒）"
                ) from exc

            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "未知错误").strip()
                raise ValueError(f"Codex CLI 调用失败: {detail[-2000:]}")

            text = ""
            if output_path.is_file():
                text = output_path.read_text(encoding="utf-8")
            if not text.strip():
                text = completed.stdout
            if not text.strip():
                raise ValueError("Codex CLI 未返回测试用例")
            return text


class LLMCaseGenerator(CodexCaseGenerator):
    """旧插件名的兼容入口；新代码应使用 CodexCaseGenerator。"""

    name = "llm"


def _build_user_message(
    requirement: Requirement,
    code_context: CodeContext | None,
    extra_prompt: str,
) -> str:
    message = f"## 需求文档\n标题: {requirement.title}"
    metadata = _requirement_metadata(requirement)
    if metadata:
        message += "\n" + "\n".join(metadata)
    message += f"\n\n{requirement.content}"

    image_urls = requirement.extras.get("image_urls", []) if requirement.extras else []
    if image_urls:
        message += "\n\n## 需求中的图片\n"
        message += "\n".join(
            f"- 图片 {index}: {url}" for index, url in enumerate(image_urls, 1)
        )
        message += "\n图片已作为 Codex CLI 图像输入附加时，请结合截图中的界面和状态生成用例。"

    attachments = requirement.extras.get("attachments", []) if requirement.extras else []
    if attachments:
        message += "\n\n## 需求附件\n"
        message += "\n".join(
            f"- {item.get('name', '附件')}: {item.get('url', '')}"
            for item in attachments
            if isinstance(item, dict)
        )
    code_text = code_context.content if code_context else ""
    if code_text:
        message += f"\n\n## 相关代码信息\n{code_text}"
    if extra_prompt:
        message += f"\n\n## 额外要求\n{extra_prompt}"

    if code_text:
        message += (
            "\n\n请按两阶段策略生成用例：先覆盖需求文档，再根据代码分析补充需求未覆盖的"
            "异常、边界、权限和参数校验场景；两个阶段均须有产出。"
        )
    else:
        message += "\n\n请覆盖正常流程、异常场景和边界值。"
    return message


def _requirement_metadata(requirement: Requirement) -> list[str]:
    extras = requirement.extras or {}
    fields = [
        ("需求编号", extras.get("task_code")),
        ("所属项目", extras.get("project_name")),
        ("需求集合", extras.get("task_set_name")),
        ("状态", extras.get("status")),
        ("优先级", extras.get("priority")),
        ("负责人", extras.get("assignee")),
        ("创建人", extras.get("creator")),
        ("创建时间", extras.get("created_at")),
        ("更新时间", extras.get("updated_at")),
    ]
    result = [f"{label}: {value}" for label, value in fields if value not in (None, "")]
    if requirement.source_ref:
        result.append(f"来源链接: {requirement.source_ref}")
    return result


def _local_image_paths(images: list[Any]) -> list[str]:
    paths: list[str] = []
    for image in images or []:
        if not isinstance(image, (str, os.PathLike)):
            continue
        path = Path(image)
        if path.is_file():
            paths.append(str(path.resolve()))
    return paths[:20]


def _parse_case_payload(text: str) -> list[dict]:
    """解析 Structured Outputs；兼容忽略 Schema 的 OpenAI 代理响应。"""
    cleaned = _clean_json(text)
    candidates = [cleaned]

    first_object, last_object = cleaned.find("{"), cleaned.rfind("}")
    if first_object != -1 and last_object > first_object:
        candidates.append(cleaned[first_object:last_object + 1])

    first_array, last_array = cleaned.find("["), cleaned.rfind("]")
    if first_array != -1 and last_array > first_array:
        candidates.append(cleaned[first_array:last_array + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        cases = payload.get("cases") if isinstance(payload, dict) else payload
        if isinstance(cases, list) and all(isinstance(case, dict) for case in cases):
            return cases

    repaired = _try_fix_truncated_array(cleaned)
    if repaired is not None:
        return repaired
    raise ValueError(f"用例 JSON 解析失败，响应前 500 字:\n{cleaned[:500]}")


def _clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return re.sub(r",\s*([}\]])", r"\1", text)


def _try_fix_truncated_array(text: str) -> list[dict] | None:
    start = text.find("[")
    if start == -1:
        return None
    search_from = len(text)
    for _ in range(50):
        pos = text.rfind("}", start, search_from)
        if pos == -1:
            break
        candidate = text[start:pos + 1].rstrip(",").rstrip() + "\n]"
        try:
            cases = json.loads(candidate)
        except json.JSONDecodeError:
            search_from = pos
            continue
        if isinstance(cases, list) and cases and all(isinstance(case, dict) for case in cases):
            return cases
        search_from = pos
    return None
