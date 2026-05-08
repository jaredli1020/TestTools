"""LLM 用例生成器 - 通过 Anthropic API 生成测试用例"""

from __future__ import annotations

import json
import os
import re

from casecraft.core import CaseGenerator, Requirement, CodeContext, TestCase
from casecraft.core import get_config


DEFAULT_SYSTEM_PROMPT = """你是一个资深高级测试工程师，专门根据需求文档和后端代码逻辑生成高质量的测试用例。

⚠️ 核心约束（贯穿全文，违反任何一条视为生成失败）：
1. 如果同时提供了需求文档和代码分析，最终输出必须同时包含"需求文档"来源和"代码分析-xxx"来源的用例
2. 不允许生成语义重复或仅测试数据不同的用例，本质相同的场景合并为一条
3. 只输出 JSON 数组，不要任何解释文字或 markdown 包裹

## 生成策略（两阶段，都必须产出用例）

### 第一阶段：基于需求文档生成
1. 从用户视角逐句分析需求，每个功能点、业务规则、交互逻辑都必须有对应用例
2. "现状"与"期望"对比 → 生成验证新旧逻辑差异的用例
3. 需求中隐含的边界条件、异常场景也要覆盖
4. 用例来源标注为"需求文档"

### 第二阶段：基于代码分析补充（不可跳过）
仔细阅读代码，找出需求未提及但代码中存在的测试点，生成额外用例。
必须检查的维度：
- 条件分支（if/else、switch/case）→ 来源标注"代码分析-条件分支"
- 异常处理（throw/abort）→ "代码分析-异常处理"
- 验证规则（参数校验）→ "代码分析-验证规则"
- 权限配置（接口权限、角色）→ "代码分析-权限配置"
- 状态流转（状态判断逻辑）→ "代码分析-状态流转"
- 数据约束（unique/nullable/类型）→ "代码分析-数据约束"

代码分析补充的用例聚焦高价值测试点（P0/P1级别的分支和异常优先），不需要穷举每一个 if 分支，避免产出大量低价值用例。

## 测试覆盖维度（系统性检查清单）
1. 输入：必填/选填、类型、边界值（最小/最大/空值）
2. 业务规则：正常流程、规则冲突、多条件组合
3. 权限：不同角色、越权、未登录
4. 数据：数据存在/不存在/已删除/历史数据
5. 状态：初始态/中间态/终态
6. 异常：参数错误、系统异常、外部依赖异常

## 优先级判定
- P0：核心主流程、权限控制、数据安全
- P1：重要业务分支、常见异常
- P2：边界值、非核心功能
- P3：低频场景、UI/提示类

## 输出规范
JSON 数组，每个元素字段：
- 模块、用例标题、优先级(P0/P1/P2/P3)、用例类型(功能/接口/性能/安全)
- 前置条件、操作步骤(步骤间用\\n分隔)、预期结果、测试数据
- 关联接口、标签(正常流程/异常/边界值/权限)
- 用例来源(见上方来源标注规则)、备注

## 评审规范
1. 一条用例 = 一个测试点
2. 操作步骤可执行、无歧义
3. 预期结果明确具体、可验证
4. 测试数据尽量使用真实格式（如 user_id: 10001），避免模糊描述；第三方URL/token可用示例占位
5. 删除线文本 = 已废弃需求，不生成用例
6. 文档评论需结合需求理解，必要时补充用例
7. JSON 中引号用英文双引号，文本内需要引号时用单引号
"""


class LLMCaseGenerator(CaseGenerator):
    """通过 Anthropic API 生成测试用例"""

    name = "llm"

    def __init__(self, system_prompt: str | None = None, *,
                 model: str | None = None, max_tokens: int | None = None,
                 temperature: float | None = None):
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def _api_settings(self) -> dict:
        cfg = get_config().llm
        api_key = cfg.api_key or os.getenv("ANTHROPIC_API_KEY") or ""
        base_url = cfg.base_url or os.getenv("ANTHROPIC_BASE_URL") or ""

        # 回退到 Claude Code 本地配置
        if not api_key:
            settings_path = os.path.expanduser("~/.claude/settings.json")
            if os.path.isfile(settings_path):
                try:
                    with open(settings_path, "r", encoding="utf-8") as f:
                        settings = json.load(f)
                    env = settings.get("env", {})
                    api_key = env.get("ANTHROPIC_AUTH_TOKEN", "")
                    base_url = env.get("ANTHROPIC_BASE_URL", "")
                except Exception:
                    pass

        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": self._model or cfg.model,
            "max_tokens": self._max_tokens or cfg.max_tokens,
            "temperature": self._temperature if self._temperature is not None else cfg.temperature,
        }

    def generate(self, requirement: Requirement, code_context: CodeContext | None = None,
                 *, extra_prompt: str = "", **kwargs) -> list[TestCase]:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("需要安装 anthropic SDK: pip install anthropic") from e

        user_msg = f"## 需求文档\n标题: {requirement.title}\n\n{requirement.content}"
        code_text = code_context.content if code_context else ""
        if code_text:
            user_msg += f"\n\n## 相关代码信息\n{code_text}"
        if extra_prompt:
            user_msg += f"\n\n## 额外要求\n{extra_prompt}"

        if code_text:
            user_msg += (
                "\n\n请严格按照两阶段策略生成测试用例。第一阶段：基于需求文档生成功能测试用例"
                "（来源标注为'需求文档'）。第二阶段：基于上面的代码分析结果，补充需求中未覆盖"
                "的异常、边界、权限、参数校验等用例（来源标注为对应的'代码分析-xxx'）。"
                "两个阶段都必须有产出。只输出JSON数组。"
            )
        else:
            user_msg += "\n\n请基于需求文档生成完整、详尽的测试用例，覆盖正常流程、异常场景、边界值。只输出JSON数组。"

        settings = self._api_settings()
        if not settings["api_key"]:
            raise ValueError("未找到 API Key，请配置 config.yaml 的 llm.api_key 或环境变量 ANTHROPIC_API_KEY")

        client_kwargs = {"api_key": settings["api_key"]}
        if settings["base_url"]:
            client_kwargs["base_url"] = settings["base_url"]
        client = anthropic.Anthropic(**client_kwargs)

        text = ""
        try:
            with client.messages.stream(
                model=settings["model"],
                max_tokens=settings["max_tokens"],
                temperature=settings["temperature"],
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for chunk in stream.text_stream:
                    text += chunk
        except Exception as e:
            raise ValueError(f"API 调用失败: {e}") from e

        if not text:
            raise ValueError("API 返回内容为空")

        cleaned = _clean_json(text)
        try:
            raw_cases = json.loads(cleaned)
        except json.JSONDecodeError:
            raw_cases = _try_fix_truncated(cleaned)
            if raw_cases is None:
                raise ValueError(f"JSON 解析失败且无法修复，前 500 字:\n{cleaned[:500]}")

        if not isinstance(raw_cases, list):
            raise ValueError("返回的不是 JSON 数组")

        return [TestCase.from_dict(c) for c in raw_cases]


def _clean_json(text: str) -> str:
    """清理 LLM 输出，提取干净的 JSON 数组"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()

    text = text.replace("“", "'").replace("”", "'")
    text = text.replace("‘", "'").replace("’", "'")

    first = text.find("[")
    last = text.rfind("]")
    if first != -1 and last != -1 and last > first:
        text = text[first:last + 1]

    # 去掉尾逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _try_fix_truncated(text: str):
    """尝试修复被截断的 JSON 数组"""
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
            if isinstance(cases, list) and cases:
                return cases
        except json.JSONDecodeError:
            pass
        search_from = pos
    return None
