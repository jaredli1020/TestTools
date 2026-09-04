import json
import tempfile
import unittest
from pathlib import Path

from casecraft.sources import FileSource, TextSource
from casecraft.sources.titles import extract_requirement_title


class RequirementTitleTests(unittest.TestCase):
    def test_text_extracts_document_titles_without_changing_the_body(self):
        samples = [
            ("# UOB-机酒增加顺序审批配置项\n\n保存审批配置", "UOB-机酒增加顺序审批配置项"),
            ("需求标题：机票首页增加出行原因\n正文：增加必填校验", "机票首页增加出行原因"),
            ("**需求名称**：**订单取消原因展示**\n展示订单取消原因", "订单取消原因展示"),
            ("UOB-审批方式配置\n\n## 新增顺序审批\n保存后生效", "UOB-审批方式配置"),
            ("**订单审批配置**\n\n## 顺序审批\n保存后生效", "订单审批配置"),
            ("---\nauthor: test\ntitle: '酒店订单取消规则'\n---\n## 取消流程\n正文", "酒店订单取消规则"),
            ("---\nauthor: test\n---\n# 酒店订单取消规则\n正文", "酒店订单取消规则"),
            ("需求文档\n创建人：测试人员\n\n## 登录验证码校验\n正文", "登录验证码校验"),
            ("订单退款规则\n============\n退款说明", "订单退款规则"),
            (".. comment\n\n订单退款规则\n------------\n退款说明", "订单退款规则"),
            ("<!-- # 示例标题 -->\n# 实际需求标题\n正文", "实际需求标题"),
            ("```markdown\n# 示例标题\n需求标题：不要使用示例标题\n```\n# 实际需求标题", "实际需求标题"),
            ("需求描述\n用户名为空时禁止保存。并显示提示。", "用户名为空时禁止保存"),
            ("用户支持手机号登录。验证码有效期为60秒。", "用户支持手机号登录"),
            ("\ufeff\n\n# BOM 文档标题\n正文", "BOM 文档标题"),
        ]
        for content, expected in samples:
            with self.subTest(content=content):
                requirement = TextSource().parse(content)
                self.assertEqual(requirement.title, expected)
                self.assertEqual(requirement.content, content)

    def test_json_titles_are_extracted_from_both_pasted_text_and_files(self):
        samples = [
            ({"title": "订单审批配置", "content": "## 参数校验\n正文"}, "订单审批配置"),
            ({"需求标题": "机票改签规则", "description": "改签说明"}, "机票改签规则"),
            ({"title": " ", "description": "# 酒店取消规则\n正文"}, "酒店取消规则"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "untitled.json"
            for data, expected in samples:
                with self.subTest(data=data):
                    raw = json.dumps(data, ensure_ascii=False)
                    path.write_text(raw, encoding="utf-8-sig")
                    self.assertEqual(TextSource().parse(raw).title, expected)
                    self.assertEqual(FileSource().parse(str(path)).title, expected)

    def test_all_local_document_formats_prefer_body_title_over_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            for extension in ("md", "markdown", "txt", "rst"):
                with self.subTest(extension=extension):
                    path = Path(folder) / f"untitled.{extension}"
                    content = "\n" * 8 + "# 订单审批配置\n\n正文描述"
                    path.write_text(content, encoding="utf-8-sig")
                    requirement = FileSource().parse(str(path))
                    self.assertEqual(requirement.title, "订单审批配置")
                    self.assertEqual(requirement.content, content)
                    self.assertEqual(requirement.source_ref, str(path.resolve()))

    def test_local_section_filter_preserves_the_document_title(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draft.md"
            path.write_text("# 订单审批配置\n## 新增审批\n新增说明\n## 删除审批\n删除说明", encoding="utf-8")
            requirement = FileSource().parse(str(path), section="删除审批")
        self.assertEqual(requirement.title, "订单审批配置")
        self.assertEqual(requirement.content, "删除说明")

    def test_explicit_title_override_is_preserved(self):
        self.assertEqual(TextSource().parse("# 原标题", title="指定标题").title, "指定标题")

    def test_empty_or_structured_content_has_a_safe_fallback(self):
        self.assertEqual(extract_requirement_title(" \n"), "未命名需求")
        self.assertEqual(extract_requirement_title("[]", fallback="订单需求"), "订单需求")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "订单需求.json"
            path.write_text('[{"name": "规则"}]', encoding="utf-8")
            self.assertEqual(FileSource().parse(str(path)).title, "订单需求")

    def test_missing_extension_reads_unique_document_and_not_path_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "flight-prd.md"
            path.write_text("# 机票首页时间段筛选\n必须只作用于第一程", encoding="utf-8")
            requirement = FileSource().parse(str(path.with_suffix("")))
            self.assertEqual(requirement.title, "机票首页时间段筛选")
            self.assertIn("必须只作用于第一程", requirement.content)
            self.assertEqual(requirement.source_ref, str(path.resolve()))
            (Path(folder) / "flight-prd.txt").write_text("另外一个文档", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "多个同名"):
                FileSource().parse(str(path.with_suffix("")))

    def test_invalid_path_is_never_used_as_requirement_text_or_title(self):
        for path in (r"C:\missing\requirement", r"G:\docs\draft.md", "/missing/requirement"):
            with self.subTest(path=path):
                self.assertEqual(extract_requirement_title(path), "未命名需求")
                with self.assertRaisesRegex(ValueError, "文件路径"):
                    TextSource().parse(path)
                with self.assertRaisesRegex(ValueError, "不存在"):
                    FileSource().parse(path)

    def test_path_metadata_is_ignored_in_favor_of_requirement_title(self):
        for content in (
            '# C:\\docs\\draft.md\n## 机票首页时间段筛选\n筛选说明',
            '需求标题：C:\\docs\\draft.md\n# 机票首页时间段筛选\n筛选说明',
            json.dumps({"title": r"C:\docs\draft.md", "content": "# 机票首页时间段筛选"}),
        ):
            with self.subTest(content=content):
                self.assertEqual(extract_requirement_title(content), "机票首页时间段筛选")


if __name__ == "__main__":
    unittest.main()
