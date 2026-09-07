"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appPath = path.join(__dirname, "..", "casecraft", "web", "static", "app.js");
const context = vm.createContext({
  console,
  URL,
  document: { addEventListener() {} },
});
vm.runInContext(fs.readFileSync(appPath, "utf8"), context, { filename: appPath });

const evaluate = (source) => vm.runInContext(source, context);
const plain = (value) => JSON.parse(JSON.stringify(value));

assert.equal(evaluate("state.sourceMode"), "link", "default source tab must be requirement link");

for (const source of ["C:\\Users\\test\\Downloads\\draft", "G:\\docs\\draft.md", "/docs/draft"] ) {
  context.addressTask = { source_mode: "path", status: "done", source_preview: source, requirement_title: source };
  assert.equal(evaluate("taskDisplayTitle(addressTask)"), "需求标题待确认");
}
context.progressFixture = { status: "running", stage_key: "analyze", progress: 20, requested_project: "code_auto" };
assert.deepEqual(plain(evaluate("pipelineStates(progressFixture).map(step => step.status)")), ["complete", "active", "waiting", "waiting"]);
for (const [key, index] of [["parse", 0], ["analyze", 1], ["generate", 2], ["export", 3]]) {
  context.progressFixture = { status: "running", stage_key: key, progress: 5, requested_project: "code_auto" };
  const statuses = plain(evaluate("pipelineStates(progressFixture).map(step => step.status)"));
  assert.equal(statuses[index], "active");
  assert.equal(statuses.filter(status => status === "active").length, 1);
}
context.progressFixture = { status: "done", progress: 100, request: { project: null } };
assert.deepEqual(plain(evaluate("pipelineStates(progressFixture).map(step => step.status)")), ["complete", "skipped", "complete", "complete"]);
context.progressFixture = { status: "error", stage_key: "generate", progress: 68, request: { project: null } };
assert.deepEqual(plain(evaluate("pipelineStates(progressFixture).map(step => step.status)")), ["complete", "skipped", "failed", "waiting"]);
context.progressFixture = { status: "pending", progress: 0, request: { project: "code_auto" } };
assert.deepEqual(plain(evaluate("pipelineStates(progressFixture).map(step => step.status)")), ["waiting", "waiting", "waiting", "waiting"]);

const task = {
  id: "new-task",
  source: "fallback",
  source_mode: "text",
  requested_project: "fallback-project",
  output_files: { excel: "old.xlsx" },
  request: {
    source: "https://max.mongoso.com/share?itemid=T749nod",
    source_mode: "link",
    project: "code_auto",
    creator: "测试人员",
    section: "验收标准",
    branch: "feature/test",
    extra_prompt: "覆盖异常场景",
    case_scope: "core",
    skip_code: false,
    formats: ["xmind", "json"],
  },
};
context.fixtureTask = task;
assert.deepEqual(plain(evaluate("taskFormValues(fixtureTask)")), {
  hasSnapshot: true,
  source: task.request.source,
  sourceMode: "link",
  project: "code_auto",
  creator: "测试人员",
  section: "验收标准",
  branch: "feature/test",
  extraPrompt: "覆盖异常场景",
  caseScope: "core",
  skipCode: false,
  formats: ["xmind", "json"],
});

context.legacyTask = {
  source: "旧需求",
  source_mode: "path",
  requested_project: "accomy-h5",
  output_files: { json: "old.json" },
};
assert.deepEqual(plain(evaluate("taskFormValues(legacyTask)")), {
  hasSnapshot: false,
  source: "旧需求",
  sourceMode: "path",
  project: "accomy-h5",
  creator: "casecraft",
  section: "",
  branch: "",
  extraPrompt: "",
  caseScope: "all",
  skipCode: false,
  formats: ["json"],
});

context.doneTask = { id: "task-1", status: "done" };
context.failedTask = { id: "task-1", status: "error" };
assert.equal(evaluate("shouldResetGenerationForm(doneTask, { id: 'task-1', revision: 7 }, 7)"), true);
assert.equal(evaluate("shouldResetGenerationForm(failedTask, { id: 'task-1', revision: 7 }, 7)"), false);
assert.equal(evaluate("shouldResetGenerationForm(doneTask, { id: 'task-1', revision: 7 }, 8)"), false);
assert.equal(evaluate("shouldResetGenerationForm(doneTask, { id: 'another', revision: 7 }, 7)"), false);
assert.equal(evaluate("shouldResetGenerationForm(doneTask, null, 7)"), false);

// A small form-only DOM double exercises the real reset/restore functions.
function control(value = "", checked = false) {
  return {
    value, checked, defaultValue: value, defaultChecked: checked,
    hidden: false, disabled: false, open: false, textContent: "", dataset: {},
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute() {}, focus() {}, scrollIntoView() {},
    closest() { return this; },
  };
}
const elements = new Map();
for (const name of [
  "sourceText", "sourceLink", "sourcePath", "projectSelect", "sectionInput",
  "branchInput", "extraPrompt", "skipCodeInput", "creatorInput", "fileInput", "pathFileInput",
  "fileNote", "charCount", "projectHelp", "generateForm", "toast",
  "textSourcePanel", "linkSourcePanel", "pathSourcePanel", "builderPanel",
  "historyList", "downloadActions", "caseScopeInput", "generateButton",
]) {
  elements.set(`#${name}`, control(name === "creatorInput" ? "casecraft" : ""));
}
elements.set(".advanced-options", control());
const formats = ["excel", "xmind", "markdown", "json"].map((name) => control(name, name === "excel"));
const tabs = ["link", "text", "path"].map((mode) => ({ ...control(), dataset: { sourceMode: mode } }));
const get = (selector) => elements.get(selector);
context.document.querySelector = get;
context.document.querySelectorAll = (selector) => {
  if (selector === "[data-source-mode]") return tabs;
  if (selector === "input[name='formats']") return formats;
  if (selector === "input[name='formats']:checked") return formats.filter(input => input.checked);
  return [];
};
context.setTimeout = () => 1;
context.clearTimeout = () => {};
context.clearInterval = () => {};
get("#generateForm").reset = () => {
  for (const input of [...elements.values(), ...formats]) {
    input.value = input.defaultValue;
    input.checked = input.defaultChecked;
  }
};
context.fixtureConfig = { projects: { code_auto: {}, "accomy-h5": {} } };
evaluate("state.config = fixtureConfig");

// Download URLs must bypass pre-rename cached attachments for every format.
for (const [format, extension] of [["excel", "xlsx"], ["xmind", "xmind"], ["markdown", "md"], ["json", "json"]]) {
  const filename = `机酒审批配置 PRD_测试用例.${extension}`;
  context.renderDownloads({
    id: "cached-task", output_files: { [format]: `old-timestamp.${extension}` },
    download_names: { [format]: filename },
  });
  const markup = get("#downloadActions").innerHTML;
  assert.ok(markup.includes(`download="${filename}"`));
  assert.ok(markup.includes(`/download/${format}?filename=${encodeURIComponent(filename)}`));
  assert.ok(!markup.includes("old-timestamp"));
}
context.renderDownloads({ id: "legacy", output_files: { xmind: "old.xmind" } });
assert.ok(get("#downloadActions").innerHTML.includes("?v=requirement-title-v2"));
context.renderDownloads({
  id: "quoted", output_files: { xmind: "old.xmind" },
  download_names: { xmind: '需求"<内容>_测试用例.xmind' },
});
assert.ok(get("#downloadActions").innerHTML.includes('download="需求&quot;&lt;内容&gt;_测试用例.xmind"'));

// All three modes show the backend's actual requirement title, not a filename
// or raw-text preview. Keep escaping titles supplied by requirement documents.
for (const mode of ["text", "path", "link"]) {
  context.titleFixture = {
    id: `title-${mode}`, source_mode: mode, status: "done", stage: "生成完成",
    source_preview: "untitled.txt", requirement_title: "订单审批<配置>",
    case_count: 1, created_at: new Date().toISOString(),
  };
  evaluate("state.tasks = [titleFixture]");
  context.renderHistory();
  assert.ok(get("#historyList").innerHTML.includes("<strong>订单审批&lt;配置&gt;</strong>"));
  assert.ok(!get("#historyList").innerHTML.includes("untitled.txt"));
}

context.restoreTaskForm(task);
assert.equal(get("#sourceLink").value, task.request.source);
assert.equal(get("#creatorInput").value, "测试人员");
assert.equal(get("#projectSelect").value, "code_auto");
assert.equal(get("#branchInput").value, "feature/test");
assert.equal(get("#caseScopeInput").value, "core");
assert.equal(get(".advanced-options").open, true);
assert.equal(get("#skipCodeInput").disabled, true);
assert.deepEqual(formats.filter((input) => input.checked).map((input) => input.value), ["xmind", "json"]);

for (const mode of ["text", "path", "link"]) {
  const historical = { ...task, status: "done", request: { ...task.request, source_mode: mode } };
  context.restoreTaskForm(historical);
  context.handleTaskCompletion(historical);
  const sourceId = { text: "#sourceText", path: "#sourcePath", link: "#sourceLink" }[mode];
  assert.equal(evaluate("state.sourceMode"), mode);
  assert.equal(get("#caseScopeInput").value, "core");
  assert.equal(get(sourceId).value, task.request.source, "viewing a completed history task must not clear it");
}

const runningTask = { ...task, status: "running" };
const completedTask = { ...task, status: "done" };
context.restoreTaskForm(runningTask);
get("#fileInput").value = "fixture.txt";
get("#pathFileInput").value = "fixture.md";
get("#sourcePath").dataset.uploadSource = "G:\\testCase\\.uploaded_requirements\\fixture.md";
get("#fileNote").hidden = false;
get("#fileNote").textContent = "已载入 fixture.txt";
context.handleTaskCompletion(completedTask);
assert.equal(evaluate("state.sourceMode"), "link");
for (const selector of ["#sourceText", "#sourceLink", "#sourcePath", "#projectSelect", "#sectionInput", "#branchInput", "#extraPrompt", "#fileInput", "#pathFileInput"]) {
  assert.equal(get(selector).value, "", `${selector} must reset after successful generation`);
}
assert.equal(get("#creatorInput").value, "casecraft");
assert.equal(get("#fileNote").hidden, true);
assert.equal(get("#fileNote").textContent, "");
assert.equal(get("#sourcePath").dataset.uploadSource, undefined);
assert.equal(get("#charCount").textContent, "0 字");
assert.equal(get(".advanced-options").open, true);
assert.equal(get("#caseScopeInput").value, "all");
assert.equal(get("#skipCodeInput").checked, false);
assert.equal(get("#skipCodeInput").disabled, false);
assert.deepEqual(formats.filter((input) => input.checked).map((input) => input.value), ["excel"]);

get("#sourceLink").value = "next draft";
context.handleTaskCompletion(completedTask);
assert.equal(get("#sourceLink").value, "next draft", "duplicate completion must not reset again");

context.restoreTaskForm(runningTask);
get("#sourceLink").value = "edited while generating";
evaluate("state.formRevision += 1");
context.handleTaskCompletion(completedTask);
assert.equal(get("#sourceLink").value, "edited while generating");

context.restoreTaskForm(runningTask);
context.handleTaskCompletion({ ...task, status: "error" });
assert.equal(get("#sourceLink").value, task.request.source, "failed tasks preserve the form for retry");

async function testAsyncSelection() {
  context.renderTask = () => {};
  context.renderHistory = () => {};
  const pending = new Map();
  context.apiRequest = (url) => new Promise((resolve) => pending.set(url, resolve));
  const older = context.selectTask("older", { scroll: false });
  const newer = context.selectTask("newer", { scroll: false });
  pending.get("/api/tasks/newer")({ ...completedTask, id: "newer" });
  await newer;
  pending.get("/api/tasks/older")({ ...completedTask, id: "older" });
  await older;
  assert.equal(evaluate("state.activeTask.id"), "newer", "a slow old response must not override the latest selection");

  // Initial load lists history but never selects or fills the most recent task.
  context.bindEvents = () => {};
  context.renderConfig = () => {};
  context.setServiceState = () => {};
  context.apiRequest = async () => context.fixtureConfig;
  context.refreshTasks = async () => evaluate("state.tasks = [fixtureTask]");
  evaluate("state.activeTask = null");
  await context.init();
  assert.equal(evaluate("state.sourceMode"), "link");
  assert.equal(evaluate("state.activeTask"), null);
  assert.equal(get("#sourceLink").value, "");
  assert.equal(get("#caseScopeInput").value, "all");
  assert.equal(get(".advanced-options").open, true);
}

async function testScopeSubmission() {
  let submitted;
  context.apiRequest = async (url, options) => {
    assert.equal(url, "/api/generate");
    submitted = JSON.parse(options.body);
    throw new Error("Stop after capturing submission");
  };
  for (const scope of ["all", "core"]) {
    context.resetGenerationForm();
    context.setSourceMode("text", { focus: false });
    get("#sourceText").value = "订单审批需求";
    get("#caseScopeInput").value = scope;
    await context.submitGeneration({ preventDefault() {} });
    assert.equal(submitted.case_scope, scope);
    assert.equal(get("#caseScopeInput").value, scope, "failed submissions preserve the selected scope");
  }
  context.restoreTaskForm({ ...completedTask, request: {} });
  assert.equal(get("#caseScopeInput").value, "all", "old tasks default to all cases");
  assert.equal(get(".advanced-options").open, true);
}

testScopeSubmission().then(testAsyncSelection).then(() => {
  console.log("Web UI regression checks passed: titles, pipeline stages, defaults, reset, history restore, draft protection and stale responses");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
