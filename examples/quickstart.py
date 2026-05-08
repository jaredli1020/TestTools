"""示例：最小可用的 casecraft 应用

演示：
1. 加载配置
2. 引导默认插件
3. 通过 Pipeline 生成用例并导出
"""

import sys
import os
from pathlib import Path

# 允许从源码目录运行（无需 pip install -e .）
sys.path.insert(0, str(Path(__file__).parent.parent))

from casecraft.core import Pipeline, load_config
from casecraft.bootstrap import bootstrap_defaults
from casecraft.notifiers import ConsoleNotifier
from casecraft.core import registry


def main():
    # 1. 加载配置（会自动从 ./config.yaml / config.yaml.example 读取）
    load_config()

    # 2. 注册默认插件
    bootstrap_defaults()
    registry.register_notifier(ConsoleNotifier())

    # 3. 执行
    pipeline = Pipeline()
    requirement_text = """
    用户登录功能

    现状：系统支持邮箱+密码登录
    期望：新增手机号+短信验证码登录方式

    约束：
    - 手机号必须是 11 位，以 1 开头
    - 验证码 6 位数字，有效期 5 分钟
    - 同一手机号 1 分钟内只能发送 1 次验证码
    - 密码错误 5 次锁定账号 30 分钟
    """

    result = pipeline.run(
        requirement_text,
        formats=["markdown", "json"],
        creator="demo",
        task_name="用户登录",
    )

    print(f"\n✅ 生成 {len(result.cases)} 条用例")
    print(f"   输出: {result.output_files}")
    print(f"   统计: {result.stats}")


if __name__ == "__main__":
    main()
