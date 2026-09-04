import unittest
from unittest.mock import Mock

import requests

from casecraft.sources.mongoso import MongosoShareSource
from casecraft.core import Config, Pipeline, Registry


class _FakeResponse:
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.post_call = None

    def post(self, url, **kwargs):
        self.post_call = (url, kwargs)
        return _FakeResponse(self.payload)

    def get(self, *args, **kwargs):
        raise AssertionError("download_images=False 时不应下载图片")


class MongosoShareSourceTests(unittest.TestCase):
    def test_only_matches_strict_share_links(self):
        valid = "https://max.mongoso.com/share?itemid=T749nod"

        self.assertTrue(MongosoShareSource().match(valid))
        self.assertEqual(MongosoShareSource.extract_item_id(valid), "T749nod")
        self.assertFalse(MongosoShareSource().match("https://max.mongoso.com/layout"))
        self.assertFalse(
            MongosoShareSource().match(
                "https://example.com/share?itemid=T749nod"
            )
        )
        self.assertFalse(
            MongosoShareSource().match(
                "http://max.mongoso.com/share?itemid=T749nod"
            )
        )

    def test_parse_extracts_text_metadata_and_image_urls(self):
        payload = {
            "result": "1",
            "code": "000000",
            "data": {
                "taskId": "132919",
                "taskCode": "11052",
                "taskTitle": "订单取消原因展示",
                "taskDesc": (
                    "<p>当前结果：未展示原因</p>"
                    "<p><strong>期待结果</strong></p>"
                    "<ul><li>审批拒绝</li><li>支付超时</li></ul>"
                    '<img src="https://maxfile.mongoso.com/demo.png">'
                ),
                "directorName": "测试负责人",
                "projectName": "FCG-TMC",
                "taskSetName": "产品需求",
                "taskStatusName": "未开始",
                "priority": "1",
                "creator": "创建人",
                "createdDt": "2026-06-26 16:41:28",
                "updator": "更新人",
                "updatedDt": "2026-08-26 16:26:21",
                "fileList": [{"fileName": "验收标准.pdf", "fileUrl": "https://file.example/a"}],
                "associationTaskList": [{"taskCode": "10999", "taskTitle": "关联需求"}],
            },
        }
        session = _FakeSession(payload)
        source = MongosoShareSource(session=session, download_images=False)

        requirement = source.parse(
            "https://max.mongoso.com/share?itemid=T749nod"
        )

        self.assertEqual(requirement.title, "订单取消原因展示")
        self.assertEqual(requirement.source_type, "mongoso_share")
        self.assertEqual(requirement.extras["task_code"], "11052")
        self.assertEqual(requirement.extras["project_name"], "FCG-TMC")
        self.assertIn("当前结果：未展示原因", requirement.content)
        self.assertIn("- 审批拒绝", requirement.content)
        self.assertIn("[需求截图 1]", requirement.content)
        self.assertEqual(
            requirement.images,
            ["https://maxfile.mongoso.com/demo.png"],
        )
        self.assertEqual(requirement.extras["attachments"][0]["name"], "验收标准.pdf")
        self.assertEqual(requirement.extras["associations"][0]["code"], "10999")
        self.assertEqual(session.post_call[1]["json"]["taskId"], "T749nod")

    def test_parse_reports_expired_or_missing_share(self):
        session = _FakeSession(
            {"result": "0", "code": "404001", "msg": "分享已失效", "data": None}
        )
        source = MongosoShareSource(session=session, download_images=False)

        with self.assertRaisesRegex(ValueError, "分享已失效"):
            source.parse("https://max.mongoso.com/share?itemid=T749nod")

    def test_network_failure_stops_pipeline_before_codex_or_export(self):
        session = Mock()
        session.post.side_effect = requests.ConnectionError("connection blocked")
        source = MongosoShareSource(session=session)
        registry = Registry()
        registry.register_source(source)
        generator = Mock()
        generator.name = "codex"
        registry.register_generator(generator, default=True)
        with self.assertRaisesRegex(ValueError, "无法读取 Mongoso 需求分享链接"):
            Pipeline(registry_=registry, config=Config()).run(
                "https://max.mongoso.com/share?itemid=T749nod", skip_code=True
            )
        session.post.assert_called_once()
        session.get.assert_not_called()
        generator.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
