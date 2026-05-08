# casecraft

需求驱动的测试用例自动生成框架。从 IdreamSky testcraft 抽象而来，去除业务耦合，可作为新项目的起点。

把需求（文本/文件/飞书文档）和代码（可选）喂给 LLM，产出 Excel/XMind/Markdown/JSON 格式的测试用例。

## 核心能力

- **插件化**：Source / Analyzer / Generator / Exporter / Notifier 都是插件，注册即用
- **需求源**：文本、本地文件、飞书文档（可选）
- **代码分析**：抽象接口 + 占位实现，业务自己写语言特定分析器
- **LLM 生成**：内置 Anthropic 实现，支持两阶段策略（需求 + 代码分析）
- **多格式导出**：Excel（带样式）、XMind、Markdown、JSON
- **通知集成**：飞书群机器人 webhook + 心跳检测
- **Git Diff 回归**：基于 git diff 定位变更并生成回归用例
- **CLI + Web**：click CLI、FastAPI + SSE Web 骨架
- **GitLab 远程**：从 GitLab 拉取代码，无需本地 clone

## 目录结构

```
casecraft_framework/
├── casecraft/
│   ├── core/                # 核心数据模型 + 抽象接口 + 插件注册 + 管道
│   │   ├── models.py        # Requirement / CodeContext / TestCase
│   │   ├── interfaces.py    # 5 个插件基类
│   │   ├── registry.py      # 插件注册表
│   │   ├── pipeline.py      # 管道编排
│   │   └── config.py        # 配置加载
│   ├── sources/             # 需求源插件
│   │   ├── text.py
│   │   ├── file.py
│   │   └── feishu.py        # 可选（lark-oapi）
│   ├── analyzers/           # 代码分析器插件
│   │   ├── noop.py          # 占位实现
│   │   └── utils.py         # 关键词提取、文件遍历
│   ├── generators/          # 用例生成器插件
│   │   └── llm.py           # Anthropic API 生成器
│   ├── exporters/           # 导出器插件
│   │   ├── excel.py
│   │   ├── xmind.py
│   │   ├── markdown.py
│   │   └── json_exporter.py
│   ├── notifiers/           # 通知器插件
│   │   ├── console.py
│   │   └── feishu.py        # 飞书 webhook
│   ├── diff/                # Git Diff 回归测试
│   │   ├── base.py          # DiffAnalyzer 抽象
│   │   └── git_diff.py      # 通用 git 实现
│   ├── integrations/        # 可选集成
│   │   └── gitlab.py        # GitLab 远程读取
│   ├── web/                 # FastAPI + SSE Web 骨架
│   ├── cli.py               # click CLI
│   └── bootstrap.py         # 默认插件注册
│
├── examples/
│   ├── quickstart.py        # 最小可用示例
│   └── custom_analyzer.py   # 自定义分析器插件示例
│
├── config.yaml.example
├── pyproject.toml
└── README.md
```

## 核心模型

管道里流转的三种标准化数据：

```python
@dataclass
class Requirement:
    title: str
    content: str
    source_type: str = "text"
    images: list = []
    extras: dict = {}

@dataclass
class CodeContext:
    content: str = ""            # LLM 可直接消费的文本
    project_key: str = ""
    raw: dict = {}               # 结构化原始数据

@dataclass
class TestCase:
    data: dict = {}              # 字段由 Generator 按项目模板填充
```

## 插件接口

5 个扩展点，业务实现其中任意一个并注册即可：

```python
class RequirementSource:         # 解析需求输入
    def match(self, source) -> bool: ...
    def parse(self, source, **kw) -> Requirement: ...

class CodeAnalyzer:              # 代码上下文提取
    def match(self, project) -> bool: ...
    def analyze(self, req, project, **kw) -> CodeContext: ...

class CaseGenerator:             # 生成测试用例
    def generate(self, req, ctx, **kw) -> list[TestCase]: ...

class CaseExporter:              # 导出到文件
    def export(self, cases, path, **kw) -> str: ...

class Notifier:                  # 任务事件通知
    def on_start / on_stage / on_heartbeat / on_error / on_finish
```

## 快速开始

### 安装

```bash
cd casecraft_framework
pip install -e .
# 可选依赖
pip install -e ".[web,feishu]"
```

### 配置

```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml，至少配置 llm.api_key 或设置环境变量
export ANTHROPIC_API_KEY="..."
```

### CLI

```bash
# 从文本生成
casecraft gen "用户登录功能，支持邮箱+密码登录"

# 从文件生成
casecraft gen requirements/login.md -f all

# 指定项目做代码分析
casecraft gen requirements/login.md -p my_project

# 飞书文档（需要安装 lark-oapi + 配置 feishu.app_id）
casecraft gen https://xxx.feishu.cn/docx/xxxxx -s "登录功能"

# 预览需求解析
casecraft preview requirements/login.md

# Git Diff 回归测试
casecraft diff -p my_project -r HEAD~3

# 启动 Web 服务
casecraft web --port 8001
```

### 程序化调用

```python
from casecraft.core import Pipeline, load_config
from casecraft.bootstrap import bootstrap_defaults

load_config("config.yaml")
bootstrap_defaults()

pipeline = Pipeline()
result = pipeline.run(
    source="用户登录功能...",
    formats=["excel", "markdown"],
    project="my_project",      # 可选，做代码分析
    creator="alice",
)

print(f"生成 {len(result.cases)} 条用例")
print(f"输出文件: {result.output_files}")
print(f"统计: {result.stats}")
```

## 扩展指南

### 自定义代码分析器

继承 `CodeAnalyzer`，根据 `project["type"]` 决定是否处理：

```python
from casecraft.core import CodeAnalyzer, CodeContext, Requirement
from casecraft.analyzers.utils import extract_keywords, walk_files

class JavaSpringAnalyzer(CodeAnalyzer):
    name = "java-spring"

    def match(self, project):
        return project.get("type") == "java-spring"

    def analyze(self, req, project, **kw):
        keywords = extract_keywords(req.content)
        # ... 自己的分析逻辑
        return CodeContext(content="...", project_type=project["type"])

# 注册
from casecraft.core import registry
registry.register_analyzer(JavaSpringAnalyzer(), front=True)
```

### 自定义导出器

```python
from casecraft.exporters.base import BaseExporter

class CsvExporter(BaseExporter):
    name = "csv"
    extension = "csv"

    def export(self, cases, output_path=None, **kw):
        output_path = self._resolve_output(output_path)
        rows = self._normalize(cases)
        # ... 写 csv
        return output_path

registry.register_exporter(CsvExporter())
```

然后命令行 `casecraft gen xxx -f csv` 或 `-f all` 就会包含 csv。

### 自定义需求源

例如支持 Confluence：

```python
class ConfluenceSource(RequirementSource):
    name = "confluence"

    def match(self, source):
        return "confluence" in source and source.startswith("http")

    def parse(self, source, **kw):
        # ... 调 Confluence API
        return Requirement(title=..., content=..., source_type="confluence")

registry.register_source(ConfluenceSource(), front=True)
```

### 自定义通知器

```python
class DingTalkNotifier(Notifier):
    name = "dingtalk"

    def __init__(self, webhook): self.webhook = webhook
    def on_finish(self, task_name, case_count, output_files, **_):
        # ... 调钉钉 webhook

registry.register_notifier(DingTalkNotifier("https://..."))
```

## 管道扩展

默认 `Pipeline.run()` 调用顺序：
parse → analyze → generate → export

如果需要插入新阶段（如「代码逻辑摘要」），继承 `Pipeline` 并覆盖 `run()`：

```python
class CustomPipeline(Pipeline):
    def run(self, source, **kw):
        req = self.parse_requirement(source, ...)
        ctx = self.analyze_code(req, ...)
        ctx = self.summarize(ctx)          # 新增阶段
        cases = self.generate(req, ctx)
        return self.export(cases, ...)

    def summarize(self, ctx):
        # ... 调 LLM 压缩代码上下文
        return ctx
```

## Web 界面

`casecraft web` 启动 FastAPI + SSE 骨架，默认接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/config` | 配置 / projects / 可用格式 |
| POST | `/api/generate` | 提交生成任务 |
| GET  | `/api/tasks/{id}` | 任务状态 |
| GET  | `/api/tasks/{id}/stream` | SSE 进度推送 |
| GET  | `/api/tasks` | 历史任务 |
| GET  | `/api/tasks/{id}/download/{fmt}` | 下载输出 |

业务项目需要 UI 界面时，自行写前端 HTML 放到 `static/` 或直接集成 React/Vue。

## 约定

- 插件通过 `registry` 全局注册，`bootstrap_defaults()` 只注册内置插件
- 需求源按注册顺序 `match()` 决定归属，`TextSource` 放最后兜底
- 代码分析器同理，`NoopAnalyzer` 兜底
- 导出器按 `name` 索引，CLI `-f all` 会调用所有已注册的导出器
- 日志推荐通过 `StageListener` / `Notifier` 统一接收，框架不直接打印

## 从 testcraft 迁移要点

| testcraft 模块 | casecraft 对应 |
|----------------|----------------|
| `parser.py` | `sources/text.py`、`sources/file.py`、`sources/feishu.py` |
| `analyzer.py` + `ast_analyzer.py` + `deep_analyzer.py` | `analyzers/` 业务自实现 |
| `generator.py` | `generators/llm.py` |
| `exporter.py` | `exporters/excel.py` + `xmind.py` + `markdown.py` + `json_exporter.py` |
| `notifier.py` | `notifiers/feishu.py` + 管道内置心跳 |
| `gitlab_client.py` | `integrations/gitlab.py` |
| `diff_analyzer.py` | `diff/git_diff.py`（简化版，业务自行扩展） |
| `navigator.py`、`summarizer.py` | 业务自行实现，建议作为自定义 Pipeline 阶段 |
| `web_app.py` | `web/app.py`（无业务路由的骨架） |
| `cli.py` | `cli.py` |

## 许可

MIT
