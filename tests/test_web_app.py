import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import casecraft.web.app as web_app
from casecraft.core.config import get_config
from casecraft.core import Pipeline, Requirement, TestCase
from casecraft.generators.llm import CodexCaseGenerator
from casecraft.sources import MongosoShareSource
from casecraft.web.app import app, TaskInfo, _source_preview


class WebWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkpoints = tempfile.TemporaryDirectory()
        cls.checkpoint_patch = patch.object(web_app, "CHECKPOINT_DIR", Path(cls.checkpoints.name))
        cls.upload_patch = patch.object(web_app, "UPLOAD_DIR", Path(cls.checkpoints.name) / "uploads")
        cls.tasks_patch = patch.object(web_app, "_tasks", {})
        cls.checkpoint_patch.start()
        cls.upload_patch.start()
        cls.tasks_patch.start()
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.tasks_patch.stop()
        cls.checkpoint_patch.stop()
        cls.upload_patch.stop()
        cls.checkpoints.cleanup()

    def test_homepage_and_static_assets_are_available(self):
        page = self.client.get("/")
        script = self.client.get("/static/app.js")
        styles = self.client.get("/static/styles.css")

        self.assertEqual(page.status_code, 200)
        self.assertIn("CaseCraft", page.text)
        self.assertIn("用 Codex 生成测试用例", page.text)
        self.assertIn("需求链接", page.text)
        self.assertIn("toggleResultsButton", page.text)
        self.assertIn('class="segment active" data-source-mode="link"', page.text)
        self.assertIn('id="textSourcePanel" class="source-panel" hidden', page.text)
        self.assertIn('id="linkSourcePanel" class="source-panel">', page.text)
        self.assertIn('id="pathPickerButton"', page.text)
        self.assertIn('id="pathFileInput"', page.text)
        self.assertEqual(script.status_code, 200)
        self.assertIn("submitGeneration", script.text)
        self.assertIn("source_mode", script.text)
        self.assertIn("DEFAULT_VISIBLE_CASES = 5", script.text)
        self.assertIn("cases.slice(0, DEFAULT_VISIBLE_CASES)", script.text)
        self.assertIn('xhigh: "极高"', script.text)
        self.assertEqual(styles.status_code, 200)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", styles.text)
        self.assertIn(
            '.path-input-wrap input[type="text"], .link-input-wrap input[type="url"]',
            styles.text,
        )

    def test_health_and_config_endpoints(self):
        health = self.client.get("/api/health")
        config = self.client.get("/api/config")

        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(config.status_code, 200)
        self.assertIn("llm", config.json())
        self.assertEqual(config.json()["llm"]["reasoning_effort"], get_config().llm.reasoning_effort)
        self.assertIn("excel", config.json()["formats"])
        self.assertTrue(config.json()["projects"]["code_auto"]["auto"])
        self.assertEqual(
            config.json()["projects"]["code_auto"]["label"],
            "关联代码仓库（自动识别）",
        )

    def test_empty_source_is_rejected_before_task_creation(self):
        response = self.client.post(
            "/api/generate",
            json={"source": "   ", "formats": ["excel"]},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("请输入需求", response.json()["detail"])

    def test_browser_selected_requirement_is_stored_as_a_local_utf8_file(self):
        response = self.client.post(
            "/api/uploads",
            files={"file": ("航班筛选.md", "# 航班时间段筛选\n\n仅第一程生效".encode("utf-8"), "text/markdown")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        uploaded = Path(payload["source"])
        self.assertEqual(payload["filename"], "航班筛选.md")
        self.assertEqual(uploaded.parent, web_app.UPLOAD_DIR)
        self.assertEqual(uploaded.read_text(encoding="utf-8"), "# 航班时间段筛选\n\n仅第一程生效")

    def test_browser_upload_rejects_unsupported_or_oversized_files(self):
        invalid = self.client.post("/api/uploads", files={"file": ("需求.pdf", b"pdf", "application/pdf")})
        too_large = self.client.post(
            "/api/uploads",
            files={"file": ("需求.md", b"x" * (web_app.MAX_UPLOAD_BYTES + 1), "text/markdown")},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertIn("仅支持", invalid.json()["detail"])
        self.assertEqual(too_large.status_code, 422)
        self.assertIn("2 MB", too_large.json()["detail"])

    def test_link_mode_rejects_non_share_url(self):
        response = self.client.post(
            "/api/generate",
            json={
                "source": "https://max.mongoso.com/layout",
                "source_mode": "link",
                "formats": ["excel"],
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("需求分享链接", response.json()["detail"])

    def test_source_preview_is_single_line_and_bounded(self):
        preview = _source_preview("第一行\n第二行   第三行", limit=10)
        self.assertNotIn("\n", preview)
        self.assertTrue(preview.endswith("…"))

    def test_submitted_options_are_returned_and_persisted_for_history_restore(self):
        request = {
            "source": "https://max.mongoso.com/share?itemid=T749nod",
            "source_mode": "link",
            "project": "code_auto",
            "section": "验收标准",
            "branch": "feature/test",
            "skip_code": False,
            "formats": ["xmind", "json", "xmind"],
            "creator": "测试人员",
            "extra_prompt": "覆盖异常和边界",
        }
        with patch.object(web_app, "_run_task") as run_task:
            response = self.client.post("/api/generate", json=request)
        self.assertEqual(response.status_code, 202)
        task_id = response.json()["task_id"]
        run_task.assert_called_once()
        detail = self.client.get(f"/api/tasks/{task_id}").json()
        expected = {**request, "formats": ["xmind", "json"], "output_path": None}
        self.assertEqual(detail["request"], expected)
        checkpoint = json.loads(web_app._checkpoint_path(task_id).read_text(encoding="utf-8"))
        self.assertEqual(checkpoint["request"], expected)

        # Service restarts must preserve the snapshot even for interrupted tasks.
        web_app._tasks.pop(task_id)
        web_app._load_checkpoints()
        restored = self.client.get(f"/api/tasks/{task_id}").json()
        self.assertEqual(restored["request"], expected)

    def test_old_checkpoints_without_request_snapshot_still_load(self):
        old_task = TaskInfo(
            id="legacy-form-task", source="旧版需求文本", status="done",
            source_mode="text", requested_project="accomy-h5",
            output_files={"json": "old-result.json"},
        ).to_dict()
        old_task.pop("request")
        web_app._checkpoint_path(old_task["id"]).write_text(
            json.dumps(old_task, ensure_ascii=False), encoding="utf-8"
        )
        web_app._load_checkpoints()
        restored = self.client.get(f"/api/tasks/{old_task['id']}").json()
        self.assertEqual(restored["request"], {})
        self.assertEqual(restored["source"], "旧版需求文本")
        self.assertEqual(restored["requested_project"], "accomy-h5")

    def test_completed_tasks_persist_actual_titles_for_all_input_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "untitled.txt"
            path.write_text("需求标题：酒店退款配置\n正文：取消订单后退款。", encoding="utf-8")
            samples = [
                ("text", "# 机票订单审批配置\n正文：新增顺序审批。", "机票订单审批配置"),
                ("text", "用户名为空时禁止保存。提示用户名必填。", "用户名为空时禁止保存"),
                ("path", str(path), "酒店退款配置"),
                ("path", str(path.with_suffix("")), "酒店退款配置"),
                ("link", "https://max.mongoso.com/share?itemid=T749nod", "链接原有需求标题"),
            ]
            for mode, source, expected in samples:
                with (
                    self.subTest(mode=mode, source=source),
                    patch.object(CodexCaseGenerator, "generate", return_value=[TestCase.from_dict({
                        "用例标题": "测试用例标题不应替代需求标题", "优先级": "P1"
                    })]) as generate,
                    patch.object(Pipeline, "export", return_value=[]),
                    patch.object(MongosoShareSource, "parse", return_value=Requirement(
                        title="链接原有需求标题", content="链接正文", source_type="mongoso_share"
                    )),
                ):
                    response = self.client.post("/api/generate", json={
                        "source": source, "source_mode": mode, "skip_code": True, "formats": ["json"]
                    })
                    self.assertEqual(response.status_code, 202)
                    task_id = response.json()["task_id"]
                    detail = self.client.get(f"/api/tasks/{task_id}").json()
                    self.assertEqual(detail["status"], "done", detail["error"])
                    self.assertEqual(detail["requirement_title"], expected)
                    self.assertEqual(generate.call_args.args[0].title, expected)
                    self.assertEqual(detail["request"]["source"], source)
                    history = self.client.get("/api/tasks?limit=100").json()
                    row = next(item for item in history if item["id"] == task_id)
                    self.assertEqual(row["requirement_title"], expected)
                    web_app._tasks.pop(task_id)
                    web_app._load_checkpoints()
                    restored = self.client.get(f"/api/tasks/{task_id}").json()
                    self.assertEqual(restored["requirement_title"], expected)

    def test_bad_local_path_fails_before_creating_task_or_invoking_codex(self):
        for mode in ("path", "text"):
            with self.subTest(mode=mode), patch.object(CodexCaseGenerator, "generate") as generate:
                before = len(web_app._tasks)
                response = self.client.post("/api/generate", json={
                    "source": r"G:\definitely-missing-casecraft-folder\missing.md", "source_mode": mode,
                })
                self.assertEqual(response.status_code, 422)
                self.assertEqual(len(web_app._tasks), before)
                generate.assert_not_called()

    def test_title_and_current_stage_are_available_while_codex_is_running(self):
        def fake_generate(requirement, *args, **kwargs):
            running = next(task for task in web_app._tasks.values() if task.source == content)
            self.assertEqual(running.requirement_title, "真实文件标题")
            self.assertEqual(running.stage_key, "generate")
            self.assertIn("parse", running.completed_stages)
            self.assertIn("analyze", running.skipped_stages)
            self.assertEqual(running.requirement_source["type"], "text")
            return []

        content = "# 真实文件标题\n正文中的业务规则"
        with patch.object(CodexCaseGenerator, "generate", side_effect=fake_generate):
            response = self.client.post("/api/generate", json={"source": content, "source_mode": "text"})
        detail = self.client.get(f"/api/tasks/{response.json()['task_id']}").json()
        self.assertEqual(detail["status"], "done", detail["error"])

    def test_legacy_path_title_repair_preserves_cases_and_backups_original_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "flight-prd.md"
            path.write_text("# 机票首页时间段筛选\n真实需求正文", encoding="utf-8")
            task = TaskInfo(
                id="legacy-path-title", source=str(path.with_suffix("")), source_mode="path",
                status="done", requirement_title=str(path.with_suffix("")),
                requirement_source={"type": "text", "ref": ""},
                cases=[{"用例标题": "旧用例保留"}], output_files={"excel": "old.xlsx"},
            )
            web_app._persist_task(task)
            original = web_app._checkpoint_path(task.id).read_bytes()
            web_app._load_checkpoints()
            repaired = web_app._tasks[task.id]
            self.assertEqual(repaired.requirement_title, "机票首页时间段筛选")
            self.assertEqual(repaired.cases, task.cases)
            self.assertEqual(repaired.output_files, task.output_files)
            self.assertEqual(repaired.requirement_source["type"], "text")
            self.assertTrue(repaired.requirement_source["needs_regeneration"])
            self.assertIn("请重新生成", repaired.warning)
            backup = web_app._checkpoint_path(task.id).with_suffix(".before-title-repair.bak")
            self.assertEqual(backup.read_bytes(), original)
            web_app._load_checkpoints()
            self.assertEqual(backup.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
