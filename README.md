# casecraft

需求驱动的测试用例自动生成框架。从 IdreamSky testcraft 抽象而来，去除业务耦合，可作为新项目的起点。

把需求（文本/文件/飞书文档）和代码（可选）喂给 LLM，产出 Excel/XMind/Markdown/JSON 格式的测试用例。

## 核心能力

- **插件化**：Source / Analyzer / Generator / Exporter / Notifier 都是插件，注册即用
- **需求源**：文本、本地文件、飞书文档（可选）
- **代码分析**：抽象接口 + 占位实现，业务自己写语言特定分析器
- **本地仓库关联**：自动识别需求所属仓库，安全同步当前分支并提取相关代码
- **LLM 生成**：内置 OpenAI/Codex 实现，支持两阶段策略（需求 + 代码分析）
- **多格式导出**：Excel（带样式）、XMind、Markdown、JSON
- **通知集成**：飞书群机器人 webhook + 心跳检测
- **Git Diff 回归**：基于 git diff 定位变更并生成回归用例
- **CLI + Web**：click CLI、FastAPI + SSE、本地可视化工作台
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
│   │   └── llm.py           # OpenAI Responses API / Codex 生成器
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
export OPENAI_API_KEY="..."
```

Windows PowerShell：

```powershell
$env:OPENAI_API_KEY = "..."
```

默认生成器通过 OpenAI Responses API 调用 `gpt-5.6`，并使用 Structured Outputs
保证输出符合测试用例字段结构。可在 `config.yaml` 中调整模型和推理强度：

```yaml
llm:
  provider: openai
  model: gpt-5.6
  reasoning_effort: medium
```

如需复用本机 Codex CLI 已保存的登录而不配置 API Key，可切换为 CLI 模式：

```yaml
llm:
  provider: codex_cli
  model: gpt-5.6-sol
  cli_path: C:/Users/test/AppData/Roaming/npm/codex.cmd
  timeout: 900
```

CLI 模式要求 `codex exec --help` 能在运行 Web 服务的同一用户环境中成功执行。
它只复用 Codex CLI 的认证，不会读取或续接 Codex 桌面应用中的当前对话。

#### 后台静默生成

需求链接由 Python 后台直接读取正文并缓存图片，代码上下文由代码分析阶段提供。
Codex 生成阶段只消费这些材料，不再次打开需求、图片或附件链接。

- 每次调用使用 `--ignore-user-config`，保留已有登录状态，不修改个人 Codex 配置或复制凭证。
- 在临时工作目录运行，关闭浏览器、插件、MCP、命令执行、联网检索、Hooks 和多代理功能。
- 模型和推理强度仍以 CaseCraft 的 `config.yaml` 为准，不依赖个人 Codex 配置。
- 需求读取失败直接报告错误，不打开浏览器兜底。未附加图片及未读取附件明确标注为缺失材料，相关细节待确认。
- 生成结束清理临时目录；仅记录事件类型，不记录需求正文或工具参数。若检测到非内容工具事件，拒绝结果。

此模式已在 Codex CLI `0.149.1` 验证，需要 CLI 支持 `--ignore-user-config` 和对应功能开关。
旧版不支持时会报错，不会自动降低隔离级别。更换 CLI 后建议重新做静默生成冒烟检查。
单次配置覆盖的含义见 [Codex 官方文档](https://learn.chatgpt.com/docs/config-file/config-advanced)。

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

启动后访问 `http://127.0.0.1:8001`，即可在页面中录入需求、选择导出格式、
查看 Codex 实时生成进度、预览测试用例并下载结果。Windows 也可以直接双击
项目根目录的 `start-web.cmd`。

### 关联代码仓库

“关联项目”选择“关联代码仓库（自动识别）”后，执行顺序为：

1. 根据需求中的端类型、技术特征和四个仓库的代码路径识别所属项目；
2. 检查命中仓库的当前分支和上游分支；
3. 执行 `git fetch --prune` 获取远程最新状态；
4. 当前分支落后且工作区干净时，只执行 `git merge --ff-only`；
5. 验证当前 `HEAD` 已包含上游最新提交；
6. 从 Git 已跟踪的安全源文件中提取与需求相关的实现，再与需求一起交给 Codex。

为保护本地工作，程序不会自动切分支、stash、reset 或处理分叉历史。仓库存在可能
被更新覆盖的未提交改动、没有上游分支、处于 detached HEAD，或本地与远程已经分叉时，
任务会停止并显示原因。也可以在下拉框中手动指定四个仓库之一，用于覆盖自动识别结果。

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

`casecraft web` 启动完整的本地工作台。页面不依赖外部 CDN，支持直接输入
需求文本、在浏览器中载入本地文档、输入本机绝对路径，以及粘贴
`https://max.mongoso.com/share?itemid=...` 形式的 Mongoso MAX 需求分享链接。
分享链接由后端只读接口静默提取需求编号、标题、正文、元数据和内嵌图片，
普通 `/layout` 地址不能唯一定位需求。任务状态保存在 `.task_checkpoints/`，
服务重启后仍能查看已经完成的任务。

文本输入和本地路径生成的任务会优先使用文档中的实际需求标题，支持 Markdown
标题、`需求标题：…` / `需求名称：…`、JSON `title` 字段及纯文本首行标题。
没有明确标题时，以首条有效需求描述作为任务名；没有可用的命名内容时才回退到文件名或“未命名需求”。
标题随任务结果保存，最近任务与任务详情使用相同标题，需求链接的原标题保持不变。
在“本地路径”页点击文件夹图标可选择 `.md`、`.txt`、`.json`、`.markdown` 或 `.rst`
文件；浏览器会上传到本机 CaseCraft 服务后再读取，单个文件限制为 2 MB、UTF-8 文本格式。
本地路径模式始终读取文件，不会退回为文本输入；省略扩展名时只接受唯一的同名支持文件，
文件不存在或有多个候选时会直接提示。标题在正文解析完成后即显示，不必等待用例生成结束。
历史任务若误将文件地址当作正文，启动时会备份原记录、尝试恢复文档标题并标记需要重新生成，
不会覆盖原用例或导出文件。

生成步骤横向显示在任务摘要下方，当前步骤通过高亮、旋转指示和“进行中”标识展示，
未关联代码时明确显示“已跳过”。进度百分比按后台阶段更新，不代表模型的逐条生成进度。
可运行 `.venv\\Scripts\\python.exe tests\\preview_progress.py`，在独立的本地测试页面检查
各阶段动画和小屏布局；此页面仅使用模拟任务，不会调用模型或修改任务记录。

默认接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/health` | 本地服务健康状态 |
| GET  | `/api/config` | 配置 / projects / 可用格式 |
| POST | `/api/generate` | 提交生成任务 |
| GET  | `/api/tasks/{id}` | 任务状态 |
| GET  | `/api/tasks/{id}/stream` | SSE 进度推送 |
| GET  | `/api/tasks` | 历史任务 |
| GET  | `/api/tasks/{id}/download/{fmt}` | 下载输出 |
| DELETE | `/api/tasks/{id}` | 删除任务记录（不删除导出文件） |

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
