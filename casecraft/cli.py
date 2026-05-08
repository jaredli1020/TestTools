"""CLI 入口 - click 实现

命令：
  casecraft gen <source>       基于需求生成用例
  casecraft preview <source>   预览需求解析
  casecraft analyze <source>   预览代码分析
  casecraft diff               基于 Git Diff 生成回归用例
  casecraft web                启动 Web 服务
"""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .bootstrap import bootstrap_defaults
from .core import Pipeline, load_config, get_config, registry


console = Console()


@click.group()
@click.option("--config", "-c", default=None, help="配置文件路径")
def main(config):
    """casecraft - 需求驱动的测试用例自动生成框架"""
    load_config(config)
    bootstrap_defaults(include_console_notifier=False)


@main.command()
@click.argument("source")
@click.option("--format", "-f", "fmt", default="excel",
              help="输出格式: excel / xmind / markdown / json / all")
@click.option("--output", "-o", default=None, help="输出文件路径")
@click.option("--project", "-p", default=None, help="项目 key，用于代码分析")
@click.option("--branch", "-b", default=None, help="Git 分支（远程模式）")
@click.option("--no-code", is_flag=True, help="跳过代码分析")
@click.option("--creator", default="casecraft", help="创建人")
@click.option("--extra", "-e", default="", help="额外提示词")
@click.option("--section", "-s", default=None, help="文档章节名过滤")
@click.option("--silent", is_flag=True, help="静默模式，不发送通知")
def gen(source, fmt, output, project, branch, no_code, creator, extra, section, silent):
    """基于需求生成测试用例"""
    console.print(Panel("🔧 casecraft 测试用例生成器", style="bold blue"))

    pipeline = Pipeline()
    formats = [s.strip() for s in fmt.split(",") if s.strip()]

    with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as progress:
        task = progress.add_task("执行中...", total=None)
        try:
            result = pipeline.run(
                source,
                section=section,
                project=project,
                branch=branch,
                formats=formats,
                output_path=output,
                creator=creator,
                extra_prompt=extra,
                skip_code=no_code,
                task_name=section or source[:60],
            )
            progress.update(task, description=f"✅ 完成，{len(result.cases)} 条用例")
        except Exception as e:
            console.print(f"[red]❌ 生成失败: {e}[/red]")
            sys.exit(1)

    console.print(f"\n  📊 优先级: {result.stats.get('priorities', {})}")
    console.print(f"  🏷️  标签: {result.stats.get('tags', {})}")
    for path in result.output_files:
        console.print(f"  📁 [green]{path}[/green]")
    console.print(Panel(f"✅ 共生成 {len(result.cases)} 条测试用例", style="bold green"))


@main.command()
@click.argument("source")
@click.option("--section", "-s", default=None)
def preview(source, section):
    """预览需求解析结果（不生成用例）"""
    pipeline = Pipeline()
    req = pipeline.parse_requirement(source, section=section)
    console.print(Panel(f"📄 {req.title}", style="bold blue"))
    console.print(req.content[:2000])
    if len(req.content) > 2000:
        console.print(f"\n[dim]... 共 {len(req.content)} 字符，已截断[/dim]")


@main.command()
@click.argument("source")
@click.option("--project", "-p", default=None)
@click.option("--branch", "-b", default=None)
def analyze(source, project, branch):
    """预览代码分析结果"""
    pipeline = Pipeline()
    req = pipeline.parse_requirement(source)
    ctx = pipeline.analyze_code(req, project_key=project, branch=branch)
    console.print(Panel("🔍 代码分析结果", style="bold blue"))
    console.print(ctx.content[:3000] or "[未找到相关代码]")


@main.command()
@click.option("--project", "-p", required=True)
@click.option("--ref", "-r", default="HEAD~1")
@click.option("--format", "-f", "fmt", default="excel")
@click.option("--extra", "-e", default="")
def diff(project, ref, fmt, extra):
    """基于 Git Diff 生成回归测试用例"""
    from .diff import GitDiffAnalyzer

    cfg = get_config()
    proj = cfg.projects.get(project)
    if not proj:
        console.print(f"[red]项目 {project} 未在 config 中配置[/red]")
        sys.exit(1)
    proj = {**proj, "key": project}

    analyzer = GitDiffAnalyzer()
    diff_result = analyzer.analyze(proj, diff_ref=ref)

    if not diff_result.changed_files:
        console.print("[yellow]⚠️ 没有检测到代码变更[/yellow]")
        return

    console.print(Panel("📝 Git Diff 分析", style="bold blue"))
    console.print(diff_result.format())

    # 把 diff 结果作为需求喂给 pipeline
    from .core import Requirement, CodeContext
    from .bootstrap import registry as _reg  # noqa

    pipeline = Pipeline()
    requirement = Requirement(
        title=f"Git Diff 回归测试 ({ref})",
        content=f"基于以下代码变更生成回归测试用例：\n\n{diff_result.format()}",
        source_type="diff",
        source_ref=ref,
    )
    code_ctx = CodeContext(content=diff_result.format(), project_key=project,
                           project_type=proj.get("type", ""))

    cases = pipeline.generate(requirement, code_ctx, extra_prompt=extra)
    if not cases:
        console.print("[yellow]未生成用例[/yellow]")
        return

    formats = [s.strip() for s in fmt.split(",") if s.strip()]
    output_files = pipeline.export(cases, formats)
    for path in output_files:
        console.print(f"  📁 [green]{path}[/green]")
    console.print(Panel(f"✅ 共生成 {len(cases)} 条回归测试用例", style="bold green"))


@main.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8001, type=int)
def web(host, port):
    """启动 Web 服务（FastAPI）"""
    try:
        import uvicorn
        from .web.app import app  # noqa
    except ImportError as e:
        console.print(f"[red]需要安装 fastapi 和 uvicorn: pip install fastapi uvicorn sse-starlette[/red]")
        console.print(f"[dim]{e}[/dim]")
        sys.exit(1)

    console.print(Panel(f"🌐 casecraft Web 启动中 http://{host}:{port}", style="bold blue"))
    uvicorn.run("casecraft.web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
