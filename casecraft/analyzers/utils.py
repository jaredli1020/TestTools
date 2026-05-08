"""代码分析器基础工具 - 供业务分析器复用

提供：
- keyword 提取（中英文映射）
- 文件遍历 + 关键词过滤
- tree-sitter 基础包装（可选依赖）
"""

from __future__ import annotations

import os
import re


DEFAULT_CN_EN_MAP = {
    "用户": ["User", "user", "Admin", "Member"],
    "登录": ["Login", "login", "Auth", "auth", "Sign"],
    "注册": ["Register", "register", "SignUp", "signup"],
    "密码": ["Password", "password", "pwd"],
    "权限": ["Permission", "permission", "Role", "role"],
    "订单": ["Order", "order"],
    "支付": ["Pay", "pay", "Payment"],
    "商品": ["Goods", "goods", "Product"],
    "文件": ["File", "file", "Upload", "upload"],
    "消息": ["Message", "message", "Notify"],
    "配置": ["Config", "config", "Setting"],
    "数据": ["Data", "data"],
    "任务": ["Task", "task", "Job"],
    "报表": ["Report", "report", "Statistics"],
}


def extract_keywords(text: str, cn_en_map: dict | None = None) -> list[str]:
    """从需求文本提取关键词（英文单词 + 中英映射）"""
    cn_en_map = cn_en_map or DEFAULT_CN_EN_MAP
    keywords: set[str] = set()

    # 英文单词
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text):
        keywords.add(word)

    # 中文关键词映射到英文
    for cn, en_list in cn_en_map.items():
        if cn in text:
            keywords.update(en_list)

    return list(keywords)


def walk_files(root: str, extensions: tuple[str, ...],
               skip_dirs: tuple[str, ...] = ("vendor", "node_modules", ".git", "storage", "bootstrap/cache")) -> list[str]:
    """遍历目录下所有符合扩展名的文件路径"""
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 过滤目录
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fname in filenames:
            if fname.endswith(extensions):
                result.append(os.path.join(dirpath, fname))
    return result


def filter_files_by_keywords(files: list[str], keywords: list[str], limit: int = 30) -> list[str]:
    """按文件路径包含关键词筛选"""
    if not keywords:
        return files[:limit]
    keywords_lower = [kw.lower() for kw in keywords]
    matched = []
    for f in files:
        f_lower = f.lower()
        if any(kw in f_lower for kw in keywords_lower):
            matched.append(f)
    return matched[:limit] if matched else files[:10]


def read_file_safe(path: str, max_chars: int = 20000) -> str:
    """安全读取文件内容，过大文件会被截断"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 1)
        if len(content) > max_chars:
            content = content[:max_chars] + "\n... (文件过长已截断)"
        return content
    except (OSError, UnicodeDecodeError):
        return ""


class TreeSitterAvailable:
    """tree-sitter 可选依赖的统一检查入口"""

    _checked = False
    _available = False

    @classmethod
    def check(cls) -> bool:
        if cls._checked:
            return cls._available
        try:
            import tree_sitter  # noqa: F401
            cls._available = True
        except ImportError:
            cls._available = False
        cls._checked = True
        return cls._available
