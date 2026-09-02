"""配置管理 - YAML + 环境变量覆盖

框架配置只定义核心字段（llm/output/notify 等），业务插件配置通过
`Config.raw` 自由访问 YAML 中的任意 key。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    provider: str = "openai"
    model: str = "gpt-5.6"
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 64000
    reasoning_effort: str = "medium"
    cli_path: str = "codex"
    timeout: int = 900


@dataclass
class OutputConfig:
    default_format: str = "excel"
    output_dir: str = "./output"


@dataclass
class NotifyConfig:
    enabled: bool = False
    webhook_url: str = ""
    heartbeat_interval: int = 30
    extras: dict = field(default_factory=dict)


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    projects: dict[str, dict] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        llm_cfg = data.get("llm", {}) or {}
        output_cfg = data.get("output", {}) or {}
        notify_cfg = data.get("notify", {}) or {}
        projects = data.get("projects", {}) or {}

        return cls(
            llm=LLMConfig(
                provider=llm_cfg.get("provider", "openai"),
                model=llm_cfg.get("model", "gpt-5.6"),
                api_key=llm_cfg.get("api_key", ""),
                base_url=llm_cfg.get("base_url", ""),
                max_tokens=llm_cfg.get("max_tokens", 64000),
                reasoning_effort=llm_cfg.get("reasoning_effort", "medium"),
                cli_path=llm_cfg.get("cli_path", "codex"),
                timeout=int(llm_cfg.get("timeout", 900)),
            ),
            output=OutputConfig(
                default_format=output_cfg.get("default_format", "excel"),
                output_dir=output_cfg.get("output_dir", output_cfg.get("excel_dir", "./output")),
            ),
            notify=NotifyConfig(
                enabled=bool(notify_cfg.get("enabled")),
                webhook_url=notify_cfg.get("webhook_url", ""),
                heartbeat_interval=notify_cfg.get("heartbeat_interval", 30),
                extras={k: v for k, v in notify_cfg.items()
                        if k not in {"enabled", "webhook_url", "heartbeat_interval"}},
            ),
            projects=projects,
            raw=data,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """从原始 YAML 读取任意 key，便于业务插件访问自定义配置"""
        return self.raw.get(key, default)


_config: Config | None = None


def load_config(path: str | None = None) -> Config:
    """加载配置文件。环境变量优先级最高。"""
    global _config

    candidates = []
    if path:
        candidates.append(Path(path))
    else:
        candidates.extend([
            Path.cwd() / "config.yaml",
            Path.cwd() / "config.yml",
            Path.cwd() / "config.yaml.example",
        ])

    data: dict = {}
    for p in candidates:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            break

    # 环境变量覆盖
    data.setdefault("llm", {})
    if os.getenv("OPENAI_API_KEY"):
        data["llm"]["api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("OPENAI_BASE_URL"):
        data["llm"]["base_url"] = os.getenv("OPENAI_BASE_URL")

    _config = Config.from_dict(data)
    return _config


def get_config() -> Config:
    if _config is None:
        return load_config()
    return _config
