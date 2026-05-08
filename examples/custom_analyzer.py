"""示例：自定义代码分析器插件

演示如何继承 CodeAnalyzer 实现业务专属的代码分析，然后注册到 registry。
"""

import sys
import os
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from casecraft.core import (
    CodeAnalyzer, CodeContext, Requirement,
    Pipeline, load_config, registry,
)
from casecraft.analyzers.utils import extract_keywords, walk_files, read_file_safe
from casecraft.bootstrap import bootstrap_defaults


class PythonDjangoAnalyzer(CodeAnalyzer):
    """最小化的 Python Django 代码分析器示例"""

    name = "python-django"

    def match(self, project: dict) -> bool:
        return project.get("type") == "python-django"

    def analyze(self, requirement: Requirement, project: dict, **kwargs) -> CodeContext:
        project_path = project.get("path", "")
        if not os.path.isdir(project_path):
            return CodeContext(content=f"[项目路径不存在: {project_path}]")

        keywords = extract_keywords(requirement.content)
        py_files = walk_files(project_path, (".py",), skip_dirs=(
            "venv", ".venv", "migrations", "node_modules", ".git", "__pycache__",
        ))

        # 只取文件名命中关键词的
        relevant = [
            f for f in py_files
            if any(kw.lower() in f.lower() for kw in keywords)
        ][:10]

        parts = [f"# {project['key']} 代码分析"]
        for fpath in relevant:
            rel = os.path.relpath(fpath, project_path)
            content = read_file_safe(fpath, max_chars=3000)
            # 只保留 view / urls 相关
            urls = re.findall(r"path\(['\"](.+?)['\"],\s*(\w+)", content)
            if urls or "def " in content:
                parts.append(f"\n## {rel}\n")
                if urls:
                    parts.append("路由:")
                    for path, view in urls[:10]:
                        parts.append(f"  - {path} -> {view}")
                defs = re.findall(r"def\s+(\w+)\s*\(", content)
                if defs:
                    parts.append("函数: " + ", ".join(defs[:15]))

        return CodeContext(
            content="\n".join(parts),
            project_key=project.get("key", ""),
            project_type=project.get("type", ""),
        )


def main():
    load_config()
    bootstrap_defaults()
    # 放到最前面，优先匹配
    registry.register_analyzer(PythonDjangoAnalyzer(), front=True)

    pipeline = Pipeline()
    result = pipeline.run(
        "用户登录，支持邮箱+密码，错误 5 次锁定",
        project="my_django_project",
        formats=["markdown"],
    )
    print(f"\n✅ 生成 {len(result.cases)} 条用例")


if __name__ == "__main__":
    main()
