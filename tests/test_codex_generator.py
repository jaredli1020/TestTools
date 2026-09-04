import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from casecraft.bootstrap import bootstrap_defaults, reset
from casecraft.core import CodeContext, Requirement, registry
from casecraft.generators.llm import (
    CASE_FIELDS,
    BACKGROUND_GENERATION_INSTRUCTIONS,
    CLI_DISABLED_FEATURES,
    CodexCaseGenerator,
    LLMCaseGenerator,
    _parse_case_payload,
    _read_cli_events,
)


def _case(title="邮箱密码登录成功"):
    case = {field: "" for field in CASE_FIELDS}
    case.update(
        {
            "模块": "登录",
            "用例标题": title,
            "优先级": "P0",
            "用例类型": "功能",
            "用例来源": "需求文档",
        }
    )
    return case


class _FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(output_text=self.output_text, status="completed")


class _FakeOpenAI:
    last_instance = None
    output_text = json.dumps({"cases": [_case()]}, ensure_ascii=False)

    def __init__(self, **kwargs):
        self.client_kwargs = kwargs
        self.responses = _FakeResponses(self.output_text)
        type(self).last_instance = self


def _config(api_key="test-key", provider="openai", model="gpt-5.6"):
    return SimpleNamespace(
        llm=SimpleNamespace(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url="",
            max_tokens=4096,
            reasoning_effort="medium",
            cli_path="codex",
            timeout=60,
        )
    )


class CodexCaseGeneratorTests(unittest.TestCase):
    def test_responses_api_request_and_structured_output(self):
        fake_module = SimpleNamespace(OpenAI=_FakeOpenAI)
        with (
            patch.dict(sys.modules, {"openai": fake_module}),
            patch("casecraft.generators.llm.get_config", return_value=_config()),
        ):
            cases = CodexCaseGenerator().generate(
                Requirement(title="登录", content="支持邮箱和密码登录"),
                CodeContext(content="POST /login 校验 password 必填"),
                extra_prompt="补充未登录场景",
            )

        self.assertEqual(cases[0].get("用例标题"), "邮箱密码登录成功")
        client = _FakeOpenAI.last_instance
        self.assertEqual(client.client_kwargs, {"api_key": "test-key"})
        request = client.responses.request
        self.assertEqual(request["model"], "gpt-5.6")
        self.assertEqual(request["reasoning"], {"effort": "medium"})
        self.assertFalse(request["store"])
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        self.assertIn("相关代码信息", request["input"])
        self.assertIn("补充未登录场景", request["input"])

    def test_missing_api_key_has_actionable_error(self):
        fake_module = SimpleNamespace(OpenAI=_FakeOpenAI)
        with (
            patch.dict(sys.modules, {"openai": fake_module}),
            patch("casecraft.generators.llm.get_config", return_value=_config(api_key="")),
        ):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                CodexCaseGenerator().generate(Requirement(title="登录", content="登录需求"))

    def test_codex_cli_reuses_local_auth_and_schema(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["prompt"] = kwargs["input"]
            captured["cwd"] = kwargs["cwd"]
            captured["env"] = kwargs.get("env")
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            output_index = command.index("--output-last-message") + 1
            Path(command[output_index]).write_text(
                json.dumps({"cases": [_case("CLI 返回")]}, ensure_ascii=False),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with (
            patch(
                "casecraft.generators.llm.get_config",
                return_value=_config(
                    api_key="", provider="codex_cli", model="gpt-5.6-sol"
                ),
            ),
            patch("casecraft.generators.llm.shutil.which", return_value=None),
            patch("casecraft.generators.llm.subprocess.run", side_effect=fake_run),
        ):
            cases = CodexCaseGenerator().generate(
                Requirement(title="登录", content="登录需求")
            )

        self.assertEqual(cases[0].get("用例标题"), "CLI 返回")
        self.assertEqual(captured["command"][:2], ["codex", "exec"])
        self.assertIn("model_reasoning_effort=medium", captured["command"])
        self.assertIn("--ephemeral", captured["command"])
        self.assertIn("--output-schema", captured["command"])
        self.assertIn("登录需求", captured["prompt"])
        self.assertIn("--ignore-user-config", captured["command"])
        self.assertIn("--strict-config", captured["command"])
        self.assertIn("--skip-git-repo-check", captured["command"])
        self.assertIn("--json", captured["command"])
        self.assertIn("web_search=disabled", captured["command"])
        self.assertIn("mcp_servers={}", captured["command"])
        self.assertIn("project_doc_max_bytes=0", captured["command"])
        self.assertIn("approval_policy=never", captured["command"])
        for feature in CLI_DISABLED_FEATURES:
            index = captured["command"].index(feature)
            self.assertEqual(captured["command"][index - 1], "--disable")
        self.assertEqual(
            captured["command"][captured["command"].index("--cd") + 1], captured["cwd"]
        )
        self.assertFalse(Path(captured["cwd"]).exists(), "临时目录应在任务结束后清理")
        self.assertIsNone(captured["env"], "保留认证环境，不复制凭证或改变 CODEX_HOME")
        self.assertIn(BACKGROUND_GENERATION_INSTRUCTIONS, captured["prompt"])

    def test_codex_cli_attaches_cached_requirement_images(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["prompt"] = kwargs["input"]
            output_index = command.index("--output-last-message") + 1
            Path(command[output_index]).write_text(
                json.dumps({"cases": [_case("带截图返回")]}, ensure_ascii=False),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "requirement.png"
            image_path.write_bytes(b"image")
            requirement = Requirement(
                title="截图需求",
                content="根据截图补充测试场景",
                images=[str(image_path)],
                extras={"image_urls": ["https://maxfile.mongoso.com/demo.png"]},
            )
            with (
                patch(
                    "casecraft.generators.llm.get_config",
                    return_value=_config(api_key="", provider="codex_cli", model="gpt-5.6-sol"),
                ),
                patch("casecraft.generators.llm.shutil.which", return_value=None),
                patch("casecraft.generators.llm.subprocess.run", side_effect=fake_run),
            ):
                cases = CodexCaseGenerator().generate(requirement)

        self.assertEqual(cases[0].get("用例标题"), "带截图返回")
        self.assertIn("--image", captured["command"])
        self.assertIn(str(image_path.resolve()), captured["command"])
        self.assertIn("需求中的图片", captured["prompt"])
        self.assertIn("已附加 1 张", captured["prompt"])
        self.assertNotIn("https://maxfile.mongoso.com/demo.png", captured["prompt"])

    def test_missing_images_and_unread_attachments_are_not_claimed_as_read(self):
        fake_module = SimpleNamespace(OpenAI=_FakeOpenAI)
        with (
            patch.dict(sys.modules, {"openai": fake_module}),
            patch("casecraft.generators.llm.get_config", return_value=_config()),
        ):
            CodexCaseGenerator().generate(Requirement(
                title="已解析需求", content="订单审批",
                source_ref="https://max.mongoso.com/share?itemid=T749nod",
                extras={
                    "image_urls": ["https://maxfile.mongoso.com/demo.png"],
                    "attachments": [{"name": "验收.pdf", "url": "https://example.com/file"}],
                },
            ))
        request = _FakeOpenAI.last_instance.responses.request
        self.assertIn("后台读取", request["input"])
        self.assertIn("已附加 0 张", request["input"])
        self.assertIn("待确认", request["input"])
        self.assertIn("仅溯源，禁止访问", request["input"])
        self.assertIn("验收.pdf（仅文件名，正文未提供", request["input"])
        self.assertNotIn("https://example.com/file", request["input"])
        self.assertIn(BACKGROUND_GENERATION_INSTRUCTIONS, request["instructions"])

    def test_cli_json_events_extract_final_message_without_logging_content(self):
        payload = json.dumps({"cases": [_case("静默生成")]}, ensure_ascii=False)
        events = [
            {"type": "thread.started", "thread_id": "test"},
            {"type": "item.completed", "item": {"type": "error", "message": "private"}},
            {"type": "item.completed", "item": {"type": "reasoning", "text": "private"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": payload}},
            {"type": "turn.completed", "usage": {}},
        ]
        with self.assertLogs("casecraft.generators.llm", level="INFO") as logs:
            result = _read_cli_events("\n".join(json.dumps(event) for event in events))
        self.assertEqual(result, payload)
        self.assertNotIn("private", " ".join(logs.output))
        self.assertNotIn("静默生成", " ".join(logs.output))

    def test_cli_failed_turn_is_not_treated_as_a_successful_result(self):
        with self.assertRaisesRegex(ValueError, "未返回完整结果"):
            _read_cli_events(json.dumps({"type": "turn.failed", "error": {"message": "private"}}))

    def test_cli_rejects_tool_events_including_unknown_future_tools(self):
        for item_type in (
            "mcp_tool_call", "web_search", "command_execution", "file_change",
            "collab_agent_tool_call", "future_browser_tool",
        ):
            with self.subTest(item_type=item_type), self.assertLogs(
                "casecraft.generators.llm", level="ERROR"
            ), self.assertRaisesRegex(ValueError, "非内容工具调用"):
                _read_cli_events(json.dumps({
                    "type": "item.started", "item": {"type": item_type, "arguments": "private"}
                }))

    def test_cli_failure_does_not_retry_without_isolation(self):
        with (
            patch("casecraft.generators.llm.get_config", return_value=_config(provider="codex_cli")),
            patch("casecraft.generators.llm.shutil.which", return_value=None),
            patch("casecraft.generators.llm.subprocess.run", return_value=subprocess.CompletedProcess(
                ["codex", "exec"], 2, stdout="", stderr="unknown option --ignore-user-config"
            )) as run,
        ):
            with self.assertRaisesRegex(ValueError, "不会改用浏览器重试"):
                CodexCaseGenerator().generate(Requirement(title="测试", content="后台测试"))
        run.assert_called_once()

    def test_cli_json_final_message_is_used_when_output_file_is_absent(self):
        output = json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": json.dumps({"cases": [_case("事件返回")]})
        }})
        with (
            patch("casecraft.generators.llm.get_config", return_value=_config(provider="codex_cli")),
            patch("casecraft.generators.llm.shutil.which", return_value=None),
            patch("casecraft.generators.llm.subprocess.run", return_value=subprocess.CompletedProcess(
                ["codex", "exec"], 0, stdout=output, stderr=""
            )),
        ):
            cases = CodexCaseGenerator().generate(Requirement(title="测试", content="后台测试"))
        self.assertEqual(cases[0].get("用例标题"), "事件返回")

    def test_parser_accepts_markdown_wrapped_array_for_proxy_compatibility(self):
        payload = "```json\n" + json.dumps([_case("代理返回")], ensure_ascii=False) + "\n```"
        cases = _parse_case_payload(payload)
        self.assertEqual(cases[0]["用例标题"], "代理返回")

    def test_bootstrap_registers_codex_default_and_legacy_alias(self):
        reset()
        try:
            bootstrap_defaults()
            self.assertIsInstance(registry.get_generator(), CodexCaseGenerator)
            self.assertIsInstance(registry.get_generator("llm"), LLMCaseGenerator)
        finally:
            reset()


if __name__ == "__main__":
    unittest.main()
