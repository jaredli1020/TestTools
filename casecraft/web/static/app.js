"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  config: null,
  sourceMode: "text",
  activeTask: null,
  tasks: [],
  stream: null,
  pollTimer: null,
  toastTimer: null,
};

const formatLabels = {
  excel: "Excel",
  xmind: "XMind",
  markdown: "Markdown",
  json: "JSON",
};

const statusLabels = {
  pending: "排队中",
  running: "生成中",
  done: "已完成",
  error: "失败",
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  bindEvents();
  updateCharCount();

  try {
    state.config = await apiRequest("/api/config");
    renderConfig();
    await refreshTasks(true);
    setServiceState(true);

    if (state.tasks.length) {
      await selectTask(state.tasks[0].id, false);
    }
  } catch (error) {
    setServiceState(false);
    showToast(error.message || "无法连接 CaseCraft 本地服务", true);
  }
}

function bindEvents() {
  $$("[data-source-mode]").forEach((button) => {
    button.addEventListener("click", () => setSourceMode(button.dataset.sourceMode));
  });

  $("#sourceText").addEventListener("input", updateCharCount);
  $("#importButton").addEventListener("click", () => $("#fileInput").click());
  $("#fileInput").addEventListener("change", async (event) => {
    const [file] = event.target.files;
    if (file) await loadLocalDocument(file);
  });
  $("#exampleButton").addEventListener("click", fillExample);
  $("#projectSelect").addEventListener("change", renderProjectSelection);
  $("#generateForm").addEventListener("submit", submitGeneration);
  $("#refreshButton").addEventListener("click", () => refreshTasks());

  $("#historyList").addEventListener("click", async (event) => {
    const deleteButton = event.target.closest("[data-delete-task]");
    if (deleteButton) {
      event.stopPropagation();
      await deleteTask(deleteButton.dataset.deleteTask);
      return;
    }
    const row = event.target.closest("[data-task-id]");
    if (row) await selectTask(row.dataset.taskId);
  });

  $("#historyList").addEventListener("keydown", async (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-task-id]")) {
      event.preventDefault();
      await selectTask(event.target.dataset.taskId);
    }
  });
}

function setSourceMode(mode) {
  state.sourceMode = mode;
  $$("[data-source-mode]").forEach((button) => {
    const active = button.dataset.sourceMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#textSourcePanel").hidden = mode !== "text";
  $("#linkSourcePanel").hidden = mode !== "link";
  $("#pathSourcePanel").hidden = mode !== "path";
  const focusTarget = mode === "link" ? $("#sourceLink") : mode === "path" ? $("#sourcePath") : $("#sourceText");
  window.setTimeout(() => focusTarget?.focus(), 0);
}

async function loadLocalDocument(file) {
  if (file.size > 2 * 1024 * 1024) {
    showToast("文档超过 2 MB，请改用本地文件路径", true);
    return;
  }

  try {
    const content = await file.text();
    $("#sourceText").value = content;
    $("#fileNote").textContent = `已载入 ${file.name} · ${formatBytes(file.size)}`;
    $("#fileNote").hidden = false;
    updateCharCount();
    showToast("需求文档已载入");
  } catch (error) {
    showToast("无法读取这个文档，请确认它是文本格式", true);
  }
}

function fillExample() {
  $("#sourceText").value = `# 手机验证码登录

## 功能说明
用户可以通过手机号和短信验证码登录系统。

## 业务规则
- 手机号必须为 11 位中国大陆号码；
- 验证码为 6 位数字，60 秒内有效，同一手机号 60 秒内不可重复发送；
- 验证码连续输错 5 次后，账号锁定 10 分钟；
- 未注册手机号验证成功后自动创建账号并登录；
- 登录成功后签发访问令牌，有效期 2 小时。

## 验收标准
覆盖正常登录、验证码失效、频率限制、错误次数锁定、重复提交、弱网重试和安全场景。`;
  $("#fileNote").hidden = true;
  updateCharCount();
  $("#sourceText").focus();
}

function updateCharCount() {
  $("#charCount").textContent = `${$("#sourceText").value.length.toLocaleString("zh-CN")} 字`;
}

function renderConfig() {
  const { llm, projects, formats, generator } = state.config;
  const providerLabel = llm.provider === "codex_cli" ? "Codex CLI" : "OpenAI API";
  $("#engineBadge").innerHTML = `<span class="pulse-dot"></span>${escapeHtml(providerLabel)} · ${escapeHtml(llm.model)}`;
  $("#engineName").textContent = `${providerLabel} / ${generator}`;
  $("#engineDetails").textContent = `${llm.model} · 推理强度 ${llm.reasoning_effort || "默认"}`;

  const projectSelect = $("#projectSelect");
  Object.entries(projects).forEach(([key, project]) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = project.label || `${key} · ${project.type}`;
    projectSelect.append(option);
  });
  renderProjectSelection();

  const sortedFormats = [...formats].sort((a, b) => {
    const order = ["excel", "xmind", "markdown", "json"];
    const rank = (value) => order.includes(value) ? order.indexOf(value) : order.length;
    return rank(a) - rank(b);
  });
  $("#formatOptions").innerHTML = sortedFormats.map((format) => `
    <span class="format-option">
      <input type="checkbox" id="format-${escapeAttribute(format)}" name="formats" value="${escapeAttribute(format)}" ${format === "excel" ? "checked" : ""}>
      <label for="format-${escapeAttribute(format)}">${escapeHtml(formatLabels[format] || format)}</label>
    </span>
  `).join("");
}

async function submitGeneration(event) {
  event.preventDefault();
  const sourceFields = {
    text: "#sourceText",
    link: "#sourceLink",
    path: "#sourcePath",
  };
  const source = $(sourceFields[state.sourceMode] || "#sourceText").value.trim();
  const formats = $$("input[name='formats']:checked").map((input) => input.value);

  if (!source) {
    const emptyMessages = {
      text: "请先输入需求内容",
      link: "请粘贴需求分享链接",
      path: "请输入需求文件路径",
    };
    showToast(emptyMessages[state.sourceMode] || "请输入需求", true);
    return;
  }
  if (state.sourceMode === "link" && !isValidMongosoShareLink(source)) {
    showToast("请输入包含 itemid 的 Mongoso 需求分享链接", true);
    return;
  }
  if (!formats.length) {
    showToast("请至少选择一种导出格式", true);
    return;
  }

  const payload = {
    source,
    source_mode: state.sourceMode,
    formats,
    project: $("#projectSelect").value || null,
    branch: $("#branchInput").value.trim() || null,
    section: $("#sectionInput").value.trim() || null,
    skip_code: $("#skipCodeInput").checked,
    creator: $("#creatorInput").value.trim() || "casecraft",
    extra_prompt: $("#extraPrompt").value.trim(),
  };

  setSubmitLoading(true);
  try {
    const created = await apiRequest("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const submittedMessage = state.sourceMode === "link"
      ? (payload.project ? "正在读取需求链接，随后识别并同步代码仓库" : "正在后台读取需求链接并生成用例")
      : (payload.project ? "任务已提交，将先验证代码仓库再生成用例" : "任务已提交，Codex 正在生成用例");
    showToast(submittedMessage);
    await refreshTasks(true);
    await selectTask(created.task_id, true);
  } catch (error) {
    showToast(error.message || "提交任务失败", true);
  } finally {
    setSubmitLoading(false);
  }
}

function isValidMongosoShareLink(value) {
  try {
    const url = new URL(value);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const itemId = url.searchParams.get("itemid") || "";
    return url.protocol === "https:"
      && url.hostname.toLowerCase() === "max.mongoso.com"
      && path === "/share"
      && /^[A-Za-z0-9_-]{3,80}$/.test(itemId);
  } catch (_) {
    return false;
  }
}

function renderProjectSelection() {
  const key = $("#projectSelect").value;
  const project = state.config?.projects?.[key];
  const help = $("#projectHelp");
  const skipCode = $("#skipCodeInput");
  help.hidden = !project;
  help.textContent = project
    ? (project.description || (project.auto ? "自动识别项目并同步当前分支" : "同步并分析选中的代码仓库"))
    : "";
  skipCode.disabled = Boolean(project);
  if (project) skipCode.checked = false;
  skipCode.closest(".switch-row")?.classList.toggle("disabled", Boolean(project));
}

function setSubmitLoading(loading) {
  const button = $("#generateButton");
  button.disabled = loading;
  button.classList.toggle("loading", loading);
}

async function refreshTasks(silent = false) {
  const refreshButton = $("#refreshButton");
  refreshButton.classList.add("spinning");
  try {
    state.tasks = await apiRequest("/api/tasks?limit=30");
    renderHistory();
    if (!silent) showToast("任务列表已刷新");
  } catch (error) {
    if (!silent) showToast(error.message || "刷新失败", true);
  } finally {
    refreshButton.classList.remove("spinning");
  }
}

function renderHistory() {
  const container = $("#historyList");
  if (!state.tasks.length) {
    container.innerHTML = `<div class="history-empty">暂无生成记录，提交第一条需求开始使用。</div>`;
    return;
  }

  container.innerHTML = state.tasks.map((task) => {
    const active = state.activeTask?.id === task.id ? " selected" : "";
    const title = task.requirement_title || task.source_preview || "未命名需求";
    const canDelete = !["pending", "running"].includes(task.status);
    return `
      <div class="history-row${active}" data-task-id="${escapeAttribute(task.id)}" role="button" tabindex="0">
        <span class="history-status ${escapeAttribute(task.status)}"><i></i>${escapeHtml(statusLabels[task.status] || task.status)}</span>
        <span class="history-source"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(task.repository?.project_key ? `${task.repository.project_key} · ${task.stage}` : task.stage)} · ${escapeHtml(task.id)}</small></span>
        <span class="history-count"><strong>${Number(task.case_count || 0)}</strong> 条用例</span>
        <time class="history-time" datetime="${escapeAttribute(task.created_at)}">${escapeHtml(relativeTime(task.created_at))}</time>
        <button class="delete-button" type="button" data-delete-task="${escapeAttribute(task.id)}" aria-label="删除任务" ${canDelete ? "" : "disabled"}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v5m4-5v5"/></svg>
        </button>
      </div>`;
  }).join("");
}

async function selectTask(taskId, scroll = true) {
  closeTaskStream();
  try {
    const task = await apiRequest(`/api/tasks/${encodeURIComponent(taskId)}`);
    state.activeTask = task;
    renderTask(task);
    renderHistory();

    if (["pending", "running"].includes(task.status)) openTaskStream(task.id);
    if (scroll && window.innerWidth < 980) $("#taskState").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showToast(error.message || "读取任务失败", true);
  }
}

function renderTask(task) {
  $("#emptyState").hidden = true;
  $("#taskState").hidden = false;
  $("#activitySubtitle").textContent = task.status === "done" ? "任务已完成，可预览或下载" : "正在同步本地执行状态";

  const statusPill = $("#statusPill");
  statusPill.className = `status-pill ${task.status}`;
  statusPill.textContent = statusLabels[task.status] || task.status;

  const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
  $("#progressRing").style.setProperty("--progress", progress);
  $("#progressValue").textContent = progress;
  $("#taskIdLabel").textContent = `TASK ${task.id}`;
  $("#stageLabel").textContent = task.stage || "等待执行";
  $("#taskSourceLabel").textContent = task.requirement_title || task.source_preview || "—";

  renderPipeline(task);
  renderRepository(task);

  const errorBox = $("#errorBox");
  errorBox.hidden = task.status !== "error";
  $("#errorMessage").textContent = task.error || "生成过程发生未知错误，请检查服务日志。";

  const completionCard = $("#completionCard");
  completionCard.hidden = task.status !== "done";
  if (task.status === "done") {
    const totalSeconds = task.timings?.total;
    $("#completionMeta").textContent = `${task.case_count} 条用例${totalSeconds != null ? ` · ${formatDuration(totalSeconds)}` : ""}`;
    renderDownloads(task);
    renderResults(task);
  } else {
    $("#resultsSection").hidden = true;
  }
}

function renderRepository(task) {
  const repository = task.repository || {};
  const card = $("#repositoryCard");
  card.hidden = !repository.project_key;
  if (card.hidden) return;

  $("#repositoryName").textContent = repository.label || repository.project_key;
  $("#repositoryFramework").textContent = repository.framework || repository.path || "本地 Git 仓库";
  $("#repositoryBranch").textContent = repository.upstream
    ? `${repository.branch} → ${repository.upstream}`
    : repository.branch || "—";
  $("#repositoryCommit").textContent = repository.short_commit || "—";
  $("#repositoryFiles").textContent = repository.matched_file_count == null
    ? "提取中"
    : `${repository.matched_file_count} 个`;

  const confidenceLabels = { high: "高", medium: "中", low: "低", manual: "手动指定" };
  $("#repositoryConfidence").textContent = confidenceLabels[task.routing?.confidence] || "—";

  const verified = $("#repositoryVerified");
  if (repository.dirty || repository.ahead > 0) {
    const notes = [];
    if (repository.ahead > 0) notes.push(`本地领先 ${repository.ahead}`);
    if (repository.dirty) notes.push("含本地改动");
    verified.textContent = `远程最新 · ${notes.join(" · ")}`;
    verified.classList.add("warning");
  } else {
    verified.textContent = repository.sync_status === "fast_forwarded" ? "已快进到最新" : "已验证最新";
    verified.classList.remove("warning");
  }
}

function renderPipeline(task) {
  const steps = $$("#pipelineSteps li");
  const progress = Number(task.progress || 0);
  const activeIndex = task.status === "pending"
    ? -1
    : steps.reduce((found, step, index) => progress >= Number(step.dataset.threshold) ? index : found, -1);

  steps.forEach((step, index) => {
    step.classList.remove("active", "complete");
    if (task.status === "done" || index < activeIndex) step.classList.add("complete");
    else if (index === activeIndex && task.status === "running") step.classList.add("active");
    else if (task.status === "error" && index < activeIndex) step.classList.add("complete");
  });
}

function renderDownloads(task) {
  const entries = Object.keys(task.output_files || {});
  $("#downloadActions").innerHTML = entries.length
    ? entries.map((format) => `<a class="download-button" href="/api/tasks/${escapeAttribute(task.id)}/download/${escapeAttribute(format)}">下载 ${escapeHtml(formatLabels[format] || format)}</a>`).join("")
    : `<span class="field-hint">本次任务没有生成导出文件</span>`;
}

function renderResults(task) {
  $("#resultsSection").hidden = false;
  $("#caseTotal").textContent = Number(task.case_count || 0).toLocaleString("zh-CN");

  const cases = task.cases || [];
  const priorities = countBy(cases, "优先级");
  const types = countBy(cases, "用例类型");
  const p0p1 = (priorities.P0 || 0) + (priorities.P1 || 0);
  const totalSeconds = Number(task.timings?.total || 0);
  const primaryType = Object.entries(types).sort((a, b) => b[1] - a[1])[0];

  const stats = [
    ["用例总数", task.case_count || 0, "完整生成结果"],
    ["高优先级", p0p1, "P0 + P1"],
    ["主要类型", primaryType?.[1] || 0, primaryType?.[0] || "暂无分类"],
    ["生成耗时", totalSeconds ? formatDuration(totalSeconds) : "—", "端到端执行"],
  ];
  $("#statsGrid").innerHTML = stats.map(([label, value, hint]) => `
    <div class="stat-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong><small>${escapeHtml(hint)}</small></div>
  `).join("");

  $("#caseTableBody").innerHTML = cases.map((testCase, index) => {
    const priority = String(testCase["优先级"] || "—");
    return `
      <tr>
        <td class="case-index">${String(index + 1).padStart(2, "0")}</td>
        <td class="case-name"><strong>${escapeHtml(testCase["用例标题"] || "未命名用例")}</strong><small>${escapeHtml(testCase["模块"] || "未分类")}</small></td>
        <td><span class="priority ${escapeAttribute(priority.toLowerCase())}">${escapeHtml(priority)}</span></td>
        <td>${escapeHtml(testCase["用例类型"] || "—")}</td>
        <td>${escapeHtml(testCase["操作步骤"] || "—")}</td>
        <td>${escapeHtml(testCase["预期结果"] || "—")}</td>
      </tr>`;
  }).join("");
}

function openTaskStream(taskId) {
  closeTaskStream();
  const stream = new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/stream`);
  state.stream = stream;

  stream.addEventListener("update", (event) => {
    const task = JSON.parse(event.data);
    state.activeTask = task;
    renderTask(task);
    updateTaskSummary(task);

    if (["done", "error"].includes(task.status)) {
      closeTaskStream();
      refreshTasks(true);
      showToast(task.status === "done" ? `已生成 ${task.case_count} 条测试用例` : "任务生成失败", task.status === "error");
    }
  });

  stream.onerror = () => {
    if (state.stream !== stream) return;
    stream.close();
    state.stream = null;
    startPolling(taskId);
  };
}

function startPolling(taskId) {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const task = await apiRequest(`/api/tasks/${encodeURIComponent(taskId)}`);
      state.activeTask = task;
      renderTask(task);
      updateTaskSummary(task);
      if (["done", "error"].includes(task.status)) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        await refreshTasks(true);
      }
    } catch (_) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }, 2000);
}

function closeTaskStream() {
  if (state.stream) state.stream.close();
  state.stream = null;
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function updateTaskSummary(task) {
  const index = state.tasks.findIndex((item) => item.id === task.id);
  const summary = { ...task, cases: [] };
  if (index >= 0) state.tasks[index] = summary;
  else state.tasks.unshift(summary);
  renderHistory();
}

async function deleteTask(taskId) {
  try {
    await apiRequest(`/api/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" });
    if (state.activeTask?.id === taskId) {
      closeTaskStream();
      state.activeTask = null;
      $("#taskState").hidden = true;
      $("#emptyState").hidden = false;
      $("#resultsSection").hidden = true;
      $("#statusPill").className = "status-pill idle";
      $("#statusPill").textContent = "空闲";
      $("#activitySubtitle").textContent = "等待提交新任务";
    }
    await refreshTasks(true);
    showToast("任务记录已删除，导出文件仍保留在本地");
  } catch (error) {
    showToast(error.message || "删除失败", true);
  }
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 204) return null;

  let payload;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join("；")
      : detail || `请求失败 (${response.status})`;
    throw new Error(message);
  }
  return payload;
}

function setServiceState(online) {
  $("#engineBadge").classList.toggle("offline", !online);
  if (!online) $("#engineBadge").innerHTML = `<span class="pulse-dot"></span>本地服务未连接`;
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function countBy(items, key) {
  return items.reduce((result, item) => {
    const value = item[key] || "未知";
    result[value] = (result[value] || 0) + 1;
    return result;
  }, {});
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)} 秒`;
  return `${Math.floor(value / 60)} 分 ${Math.round(value % 60)} 秒`;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function relativeTime(value) {
  const date = new Date(value);
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
