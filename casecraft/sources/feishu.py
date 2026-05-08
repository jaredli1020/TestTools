"""飞书文档需求源 - 可选插件，需要安装 lark-oapi

业务项目通过 FeishuDocSource(app_id, app_secret) 实例化并注册到 registry。
读取飞书文档块结构，支持按标题筛选、图片识别占位、评论提取。
"""

from __future__ import annotations

import re
from typing import Any

from casecraft.core import RequirementSource, Requirement


class FeishuDocSource(RequirementSource):
    """飞书文档解析器 - 支持 docx 和 wiki 链接"""

    name = "feishu_doc"

    def __init__(self, app_id: str, app_secret: str,
                 token_provider=None, image_handler=None):
        """
        Args:
            app_id / app_secret: 飞书应用凭证
            token_provider: 可选 callable，返回 [{"access_token": "..."}, ...]
                用于多用户授权读取，失败后回退应用 token
            image_handler: 可选 callable(client, doc_id, image_tokens, request_option) -> list[str]
                用于下载图片 + 视觉模型识别，未提供则返回占位文本
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.token_provider = token_provider
        self.image_handler = image_handler

    def match(self, source: str) -> bool:
        if not isinstance(source, str):
            return False
        return "feishu.cn" in source or "larksuite.com" in source

    def parse(self, source: str, *, section: str | None = None, **kwargs) -> Requirement:
        try:
            import lark_oapi as lark
        except ImportError as e:
            raise RuntimeError("需要安装 lark-oapi: pip install lark-oapi") from e

        doc_id = _extract_doc_id(source)
        if not doc_id:
            raise ValueError(f"无法从链接提取文档 ID: {source}")

        user_tokens = []
        if self.token_provider:
            try:
                user_tokens = self.token_provider() or []
            except Exception:
                pass

        last_error = None
        for token_info in user_tokens:
            try:
                return self._parse_with_token(doc_id, source, section, token_info.get("access_token"))
            except Exception as e:
                last_error = e
                continue

        try:
            return self._parse_with_token(doc_id, source, section, None)
        except Exception as e:
            if last_error:
                raise RuntimeError(f"所有授权用户都无权限读取该文档。最后错误: {e}") from e
            raise

    def _parse_with_token(self, doc_id: str, url: str, section: str | None, user_token: str | None) -> Requirement:
        import lark_oapi as lark
        from lark_oapi.api.docx.v1 import (
            RawContentDocumentRequest,
            ListDocumentBlockRequest,
        )
        from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest
        from lark_oapi.api.drive.v1 import ListFileCommentRequest

        client = lark.Client.builder().app_id(self.app_id).app_secret(self.app_secret).build()

        request_option = None
        if user_token:
            request_option = lark.RequestOption.builder().user_access_token(user_token).build()

        # wiki 链接先换取 document_id
        if "/wiki/" in url:
            wiki_req = GetNodeSpaceRequest.builder().token(doc_id).build()
            wiki_resp = client.wiki.v2.space.get_node(wiki_req, option=request_option)
            if wiki_resp.success() and getattr(wiki_resp.data, "node", None):
                doc_id = wiki_resp.data.node.obj_token
            elif not wiki_resp.success():
                raise RuntimeError(f"Wiki 节点获取失败: code={wiki_resp.code}, msg={wiki_resp.msg}")

        # 获取全部块
        blocks = self._get_all_blocks(client, doc_id, request_option,
                                      ListDocumentBlockRequest)

        if not blocks:
            # 回退到纯文本
            req = RawContentDocumentRequest.builder().document_id(doc_id).build()
            resp = client.docx.v1.document.raw_content(req, option=request_option)
            if not resp.success():
                raise RuntimeError(f"飞书文档获取失败: code={resp.code}, msg={resp.msg}")
            return Requirement(
                title=f"飞书文档 {doc_id}",
                content=resp.data.content if resp.data else "",
                source_type="feishu_doc",
                source_ref=url,
                extras={"doc_id": doc_id},
            )

        parsed = self._parse_blocks(blocks, section)

        image_descs: list[str] = []
        if parsed["image_tokens"] and self.image_handler:
            try:
                image_descs = self.image_handler(client, doc_id, parsed["image_tokens"], request_option) or []
            except Exception:
                image_descs = []

        comments = self._get_comments(client, doc_id, request_option, ListFileCommentRequest)

        content_parts = [parsed["text"]]
        if image_descs:
            content_parts.append("\n\n## 文档中的图片内容")
            for i, desc in enumerate(image_descs, 1):
                content_parts.append(f"\n### 图片 {i}\n{desc}")
        if comments:
            content_parts.append("\n\n## 文档评论（需结合需求补充到用例中）\n" + comments)

        title = parsed.get("doc_title") or f"飞书文档 {doc_id}"
        if section:
            title = f"{title} - {section}"

        return Requirement(
            title=title,
            content="\n".join(content_parts),
            source_type="feishu_doc",
            source_ref=url,
            images=image_descs,
            extras={"doc_id": doc_id, "comments": comments},
        )

    # ---------- helpers ----------

    def _get_all_blocks(self, client, doc_id, request_option, ListDocumentBlockRequest):
        all_blocks = []
        page_token = None
        while True:
            builder = ListDocumentBlockRequest.builder().document_id(doc_id).page_size(500)
            if page_token:
                builder = builder.page_token(page_token)
            resp = client.docx.v1.document_block.list(builder.build(), option=request_option)
            if not resp.success():
                return []
            if resp.data and resp.data.items:
                all_blocks.extend(resp.data.items)
            if resp.data and resp.data.has_more:
                page_token = resp.data.page_token
            else:
                break
        return all_blocks

    def _parse_blocks(self, blocks: list, section: str | None) -> dict:
        text_parts: list[str] = []
        image_tokens: list[str] = []
        doc_title = ""

        in_section = section is None
        section_level = 0
        section_clean = re.sub(r"[^\w\s]", "", section).strip().lower() if section else ""

        for block in blocks:
            block_type = getattr(block, "block_type", None)

            if block_type == 1:  # Page
                page = getattr(block, "page", None)
                if page:
                    doc_title = _extract_text_from_elements(page)
                continue

            heading_level = _get_heading_level(block_type)
            if heading_level:
                heading_text = _extract_heading_text(block, block_type)
                if section:
                    heading_clean = re.sub(r"[^\w\s]", "", heading_text).strip().lower()
                    if not in_section:
                        if section_clean in heading_clean or heading_clean in section_clean:
                            in_section = True
                            section_level = heading_level
                            continue
                    else:
                        # 当前处于目标 section 中，遇到同级或更高级标题则退出
                        if heading_level <= section_level:
                            break
                if in_section:
                    text_parts.append(("#" * heading_level) + " " + heading_text)
                continue

            if not in_section:
                continue

            text = _extract_block_text(block, block_type)
            if text:
                text_parts.append(text)

            image_token = _extract_image_token(block, block_type)
            if image_token:
                image_tokens.append(image_token)
                text_parts.append(f"[图片 {len(image_tokens)}]")

        return {
            "text": "\n".join(text_parts),
            "image_tokens": image_tokens,
            "doc_title": doc_title,
        }

    def _get_comments(self, client, doc_id, request_option, ListFileCommentRequest) -> str:
        comments: list[str] = []
        page_token = None
        while True:
            builder = ListFileCommentRequest.builder().file_token(doc_id).file_type("docx").page_size(100)
            if page_token:
                builder = builder.page_token(page_token)
            try:
                resp = client.drive.v1.file_comment.list(builder.build(), option=request_option)
            except Exception:
                break
            if not resp.success():
                break
            if resp.data and resp.data.items:
                for comment in resp.data.items:
                    if getattr(comment, "is_solved", False):
                        continue
                    quote = getattr(comment, "quote", "") or ""
                    reply_list = getattr(comment, "reply_list", None)
                    reply_texts = []
                    if reply_list and getattr(reply_list, "replies", None):
                        for reply in reply_list.replies:
                            content_obj = getattr(reply, "content", None)
                            if not content_obj:
                                continue
                            for elem in getattr(content_obj, "elements", None) or []:
                                text_run = getattr(elem, "text_run", None)
                                if text_run and getattr(text_run, "content", ""):
                                    reply_texts.append(text_run.content)
                    if reply_texts:
                        entry = f"针对「{quote}」的评论：\n" if quote else ""
                        entry += "\n".join(reply_texts)
                        comments.append(entry)
            if resp.data and getattr(resp.data, "has_more", False):
                page_token = resp.data.page_token
            else:
                break
        return "\n\n".join(f"- {c}" for c in comments) if comments else ""


def _extract_doc_id(url: str) -> str | None:
    for pattern in (r"/docx/([a-zA-Z0-9]+)", r"/wiki/([a-zA-Z0-9]+)", r"/doc/([a-zA-Z0-9]+)"):
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def _get_heading_level(block_type: int) -> int:
    HEADING_MAP = {3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7, 10: 8, 11: 9}
    return HEADING_MAP.get(block_type, 0)


def _extract_text_from_elements(elements_holder: Any) -> str:
    elements = getattr(elements_holder, "elements", None)
    if not elements:
        return ""
    texts = []
    for elem in elements:
        text_run = getattr(elem, "text_run", None)
        if text_run and getattr(text_run, "content", None):
            texts.append(text_run.content)
    return "".join(texts)


def _extract_block_text(block, block_type) -> str:
    for attr in ("text", "bullet", "ordered", "quote", "code", "todo"):
        holder = getattr(block, attr, None)
        if holder:
            text = _extract_text_from_elements(holder)
            if text:
                return text
    return ""


def _extract_heading_text(block, block_type) -> str:
    for level in range(1, 10):
        heading = getattr(block, f"heading{level}", None)
        if heading:
            return _extract_text_from_elements(heading)
    return ""


def _extract_image_token(block, block_type) -> str | None:
    if block_type != 27:
        return None
    image = getattr(block, "image", None)
    if image:
        return getattr(image, "token", None)
    return None
