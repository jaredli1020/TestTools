import unittest

from fastapi.testclient import TestClient

from casecraft.web.app import app, _source_preview


class WebWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_homepage_and_static_assets_are_available(self):
        page = self.client.get("/")
        script = self.client.get("/static/app.js")

        self.assertEqual(page.status_code, 200)
        self.assertIn("CaseCraft", page.text)
        self.assertIn("用 Codex 生成测试用例", page.text)
        self.assertIn("需求链接", page.text)
        self.assertEqual(script.status_code, 200)
        self.assertIn("submitGeneration", script.text)
        self.assertIn("source_mode", script.text)

    def test_health_and_config_endpoints(self):
        health = self.client.get("/api/health")
        config = self.client.get("/api/config")

        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(config.status_code, 200)
        self.assertIn("llm", config.json())
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


if __name__ == "__main__":
    unittest.main()
