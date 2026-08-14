import { marked } from "/vendor/marked.js";
import DOMPurify from "/vendor/purify.js";

marked.setOptions({ gfm: true, breaks: false });

const TOKEN = document
  .querySelector('meta[name="scribe-token"]')
  .getAttribute("content");

const stream = document.getElementById("stream");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const stopButton = document.getElementById("stop");
const resetButton = document.getElementById("reset");
const statusLabel = document.getElementById("status");
const modelLabel = document.getElementById("model");
const capsLabel = document.getElementById("caps");
const sessionLabel = document.getElementById("session");
const modelSelect = document.getElementById("model-select");
const thinkingToggle = document.getElementById("show-thinking");
const fileInput = document.getElementById("file-input");
const fileStatus = document.getElementById("file-status");
const fileList = document.getElementById("file-list");
const picker = document.getElementById("picker");
const pickerSources = document.getElementById("picker-sources");
const pickerCount = document.getElementById("picker-count");
const pickerList = document.getElementById("picker-list");
const refRow = document.getElementById("ref-row");

let sessionId = null;
let appSessionId = null;
let appFiles = [];
let appSessionReady = false;
let selectedModel = "";
let controller = null;
/** scope -> { wrap, body, raw, dirty } */
let bubbles = new Map();
/** scope -> { body, label, raw, dirty } */
let thinkings = new Map();
/** tool_use_id -> summary 节点 */
let toolCards = new Map();

/*
 * 引用选择器。核心约束：候选集永远留在服务端，按 @ 触发后按需分页拉取，
 * 模型只会看到用户选中后插入的 `@type:value` 标记。
 */
// 必须和 app/references.mjs 里的同名常量保持一致，否则前后端认定的引用范围会错位。
const REFERENCE_TERMINATORS = "，。、；：！？“”‘’（）《》【】…—～";
const REFERENCE_PATTERN = new RegExp(
  `@([a-z][a-z0-9_]*):([^\\s@${REFERENCE_TERMINATORS}]+)`,
  "g",
);
const PICKER_PAGE = 20;

let sources = [];
let pickerOpen = false;
let pickerSource = "";
let pickerItems = [];
let pickerActive = 0;
let pickerTotal = 0;
let pickerQuery = "";
/** @ 在 textarea 里的位置，插入时要把整段 @查询词 换成引用。 */
let pickerAnchor = -1;
let pickerSequence = 0;
let pickerLoading = false;

function encodeReferenceValue(value) {
  return value.replace(
    /[%\s@]/g,
    (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function decodeReferenceValue(value) {
  return value.replace(/%([0-9a-fA-F]{2})/g, (_, hex) =>
    String.fromCharCode(Number.parseInt(hex, 16)),
  );
}

/** 模型输出是不可信内容，渲染前必须过一遍 DOMPurify。 */
function renderMarkdown(target, raw) {
  target.innerHTML = DOMPurify.sanitize(marked.parse(raw));
}

function scrolledToBottom() {
  return stream.scrollHeight - stream.scrollTop - stream.clientHeight < 120;
}

function append(node) {
  const stick = scrolledToBottom();
  stream.append(node);
  if (stick) {
    stream.scrollTop = stream.scrollHeight;
  }
  return node;
}

function clearEmpty() {
  stream.querySelector(".empty")?.remove();
}

function setBusy(busy) {
  sendButton.disabled = busy || !appSessionReady;
  input.disabled = busy || !appSessionReady;
  fileInput.disabled = busy || !appSessionReady;
  modelSelect.disabled = busy || !appSessionReady;
  stopButton.hidden = !busy;
  statusLabel.textContent = busy ? "运行中…" : "";
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const PREVIEWABLE_TEXT = /\.(md|txt|csv|json|log|ya?ml)$/i;
const PREVIEWABLE_IMAGE = /\.(png|jpe?g|gif|webp)$/i;

/** token 只在请求头里，所以文件一律用 fetch 取回再转 blob，不放进 URL。 */
async function fetchFileBlob(file) {
  const response = await fetch(
    `/api/session/${appSessionId}/files/${encodeURIComponent(file.name)}`,
    { headers: { "x-scribe-token": TOKEN } },
  );
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.blob();
}

async function downloadFile(file) {
  const url = URL.createObjectURL(await fetchFileBlob(file));
  const link = document.createElement("a");
  link.href = url;
  link.download = file.originalName;
  link.click();
  URL.revokeObjectURL(url);
}

async function previewFile(file) {
  const blob = await fetchFileBlob(file);
  const card = document.createElement("details");
  card.className = "card preview";
  card.open = true;
  const summary = document.createElement("summary");
  const title = document.createElement("strong");
  title.textContent = file.originalName;
  summary.append(title);
  card.append(summary);

  if (PREVIEWABLE_IMAGE.test(file.originalName)) {
    const image = document.createElement("img");
    image.className = "preview-image";
    image.alt = file.originalName;
    image.src = URL.createObjectURL(blob);
    card.append(image);
  } else {
    const text = await blob.text();
    const body = document.createElement("div");
    body.className = "md preview-body";
    // 文件内容不可信，Markdown 渲染前必须过 DOMPurify。
    renderMarkdown(body, text);
    card.append(body);
  }

  clearEmpty();
  append(card);
}

function fileAction(label, title, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "chip-action";
  button.textContent = label;
  button.title = title;
  button.addEventListener("click", () => {
    handler().catch((error) => {
      fileStatus.textContent = error.message;
    });
  });
  return button;
}

function renderFiles() {
  fileList.replaceChildren();
  for (const file of appFiles) {
    const chip = document.createElement("span");
    chip.className = file.source === "generated" ? "file-chip made" : "file-chip";

    const label = document.createElement("span");
    label.className = "chip-name";
    label.textContent = `${file.originalName} · ${formatBytes(file.bytes)}`;
    label.title = `${file.originalName} · ${formatBytes(file.bytes)}${
      file.source === "generated" ? " · 模型生成" : ""
    }`;
    chip.append(label);

    if (
      PREVIEWABLE_TEXT.test(file.originalName) ||
      PREVIEWABLE_IMAGE.test(file.originalName)
    ) {
      chip.append(fileAction("预览", "在对话区预览", () => previewFile(file)));
    }
    chip.append(fileAction("下载", "下载到本机", () => downloadFile(file)));

    fileList.append(chip);
  }
  fileStatus.textContent = appFiles.length
    ? `${appFiles.length} 个文件`
    : "本会话文件";
}

async function loadSources() {
  const response = await fetch("/api/sources", {
    headers: { "x-scribe-token": TOKEN },
  });
  if (!response.ok) return;
  sources = (await response.json()).sources;
  pickerSource = sources[0]?.type || "";
  renderSourceTabs();
}

function renderSourceTabs() {
  pickerSources.replaceChildren();
  for (const source of sources) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "picker-source";
    tab.textContent = source.label;
    tab.title = source.hint;
    tab.setAttribute("aria-selected", String(source.type === pickerSource));
    tab.addEventListener("mousedown", (event) => {
      // mousedown 而非 click：click 之前 textarea 会先失焦，面板已经关了。
      event.preventDefault();
      switchSource(source.type);
    });
    pickerSources.append(tab);
  }
}

/**
 * 只请求当前一页。offset 用于滚动加载，limit 由服务端再夹一次上限，
 * 因此前端不可能一次把整张表拉下来。
 */
async function fetchOptions(source, queryText, offset) {
  const params = new URLSearchParams({
    source,
    q: queryText,
    limit: String(PICKER_PAGE),
    offset: String(offset),
  });
  const response = await fetch(`/api/options?${params}`, {
    headers: { "x-scribe-token": TOKEN },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json();
}

function setPickerMessage(className, text) {
  const line = document.createElement("li");
  line.className = className;
  line.textContent = text;
  pickerList.replaceChildren(line);
}

/** 高亮命中片段。标签是路径和包名，按文本节点拼装，不走 innerHTML。 */
function labelNode(label, needle) {
  const wrap = document.createElement("span");
  wrap.className = "picker-label";
  const at = needle ? label.toLowerCase().indexOf(needle.toLowerCase()) : -1;

  if (at === -1) {
    wrap.textContent = label;
    return wrap;
  }

  wrap.append(document.createTextNode(label.slice(0, at)));
  const hit = document.createElement("mark");
  hit.textContent = label.slice(at, at + needle.length);
  wrap.append(hit, document.createTextNode(label.slice(at + needle.length)));
  return wrap;
}

function renderPickerItems() {
  if (!pickerItems.length) {
    setPickerMessage("picker-empty", pickerLoading ? "搜索中…" : "没有匹配项");
    pickerCount.textContent = "";
    return;
  }

  pickerList.replaceChildren();
  pickerItems.forEach((item, index) => {
    const row = document.createElement("li");
    row.className = index === pickerActive ? "picker-item active" : "picker-item";
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", String(index === pickerActive));
    row.append(labelNode(item.label, pickerQuery));
    row.addEventListener("mousedown", (event) => {
      event.preventDefault();
      insertReference(item);
    });
    pickerList.append(row);
  });

  pickerCount.textContent = `${pickerItems.length} / ${pickerTotal}`;
}

async function refreshPicker({ append: appendPage = false } = {}) {
  if (!pickerSource) return;
  const ticket = ++pickerSequence;
  pickerLoading = true;

  if (!appendPage && !pickerItems.length) {
    setPickerMessage("picker-loading", "搜索中…");
  }

  try {
    const page = await fetchOptions(
      pickerSource,
      pickerQuery,
      appendPage ? pickerItems.length : 0,
    );
    // 输入变化很快，过期响应必须丢掉，否则列表会闪回旧结果。
    if (ticket !== pickerSequence) return;

    pickerTotal = page.total;
    pickerItems = appendPage ? [...pickerItems, ...page.items] : page.items;
    if (!appendPage) pickerActive = 0;
    // 必须先落 loading 再渲染：否则空结果会被画成“搜索中…”并永远停在那里。
    pickerLoading = false;
    renderPickerItems();
  } catch (error) {
    if (ticket === pickerSequence) {
      pickerLoading = false;
      setPickerMessage("picker-empty", error.message);
    }
  }
}

let pickerTimer = null;

function schedulePickerRefresh() {
  clearTimeout(pickerTimer);
  pickerTimer = setTimeout(() => refreshPicker(), 120);
}

function openPicker() {
  pickerOpen = true;
  picker.hidden = false;
}

function closePicker() {
  pickerOpen = false;
  picker.hidden = true;
  pickerAnchor = -1;
  pickerItems = [];
  pickerQuery = "";
  pickerTotal = 0;
  clearTimeout(pickerTimer);
}

function switchSource(type) {
  if (!type || type === pickerSource) return;
  pickerSource = type;
  pickerItems = [];
  renderSourceTabs();
  refreshPicker();
  input.focus();
}

function cycleSource(step) {
  const index = sources.findIndex((item) => item.type === pickerSource);
  const next = sources[(index + step + sources.length) % sources.length];
  if (next) switchSource(next.type);
}

/**
 * 从光标往前找触发用的 @。前面必须是行首或空白，否则邮箱地址会误触发。
 * 支持 `@file:app/se` 这种写法直接锁定数据源。
 */
function detectTrigger() {
  const caret = input.selectionStart;
  const before = input.value.slice(0, caret);
  const at = before.lastIndexOf("@");

  if (at === -1) return null;
  if (at > 0 && !/\s/.test(before[at - 1])) return null;

  const typed = before.slice(at + 1);
  if (/\s/.test(typed)) return null;

  const scoped = typed.match(/^([a-z][a-z0-9_]*):(.*)$/);
  if (scoped && sources.some((item) => item.type === scoped[1])) {
    return { at, source: scoped[1], query: decodeReferenceValue(scoped[2]) };
  }

  return { at, source: null, query: typed };
}

function syncPicker() {
  const trigger = detectTrigger();

  if (!trigger) {
    if (pickerOpen) closePicker();
    return;
  }

  // 数据源也要纳入变化判断：只比查询词的话，把 @file:x 改成 @pkg:x
  // 会留着上一个数据源的结果，标签页和列表对不上。
  let switched = false;
  if (trigger.source && trigger.source !== pickerSource) {
    pickerSource = trigger.source;
    pickerItems = [];
    renderSourceTabs();
    switched = true;
  }

  const changed = switched || trigger.query !== pickerQuery;
  pickerAnchor = trigger.at;
  pickerQuery = trigger.query;

  if (!pickerOpen) {
    openPicker();
    refreshPicker();
    return;
  }
  if (changed) schedulePickerRefresh();
}

/** 把 `@查询词` 整段替换成规范引用，光标落在引用之后并补一个空格。 */
function insertReference(item) {
  if (pickerAnchor < 0) return;
  const caret = input.selectionStart;
  const before = input.value.slice(0, pickerAnchor);
  const after = input.value.slice(caret);
  const insert = `${item.reference} `;

  input.value = `${before}${insert}${after}`;
  const position = before.length + insert.length;
  input.setSelectionRange(position, position);
  // 先关面板再渲染 chip：renderRefRow 会跳过 pickerAnchor 上那一条。
  closePicker();
  renderRefRow();
  input.focus();
}

/** 引用清单从 textarea 内容现算，不另存一份状态，避免两边不同步。 */
function renderRefRow() {
  const seen = new Set();
  refRow.replaceChildren();

  for (const match of input.value.matchAll(REFERENCE_PATTERN)) {
    // 正在输入的那一条归面板显示，否则半截查询词会先冒出一个假 chip。
    if (pickerOpen && match.index === pickerAnchor) continue;

    const type = match[1];
    const value = decodeReferenceValue(match[2]);
    const key = `${type}:${value}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const source = sources.find((item) => item.type === type);
    const chip = document.createElement("span");
    chip.className = source ? "ref-chip" : "ref-chip bad";
    chip.title = source ? `${source.label}：${value}` : `未知引用类型：${type}`;

    const label = document.createElement("span");
    label.className = "chip-name";
    label.textContent = value;
    chip.append(label);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = "移除这个引用";
    remove.addEventListener("click", () => {
      input.value = input.value.split(match[0]).join("").replace(/ {2,}/g, " ").trim();
      renderRefRow();
      input.focus();
    });
    chip.append(remove);
    refRow.append(chip);
  }
}

/** 用户气泡里把引用标记显示成实体，和 composer 里的观感一致。 */
function renderUserText(target, text) {
  target.replaceChildren();
  let at = 0;

  for (const match of text.matchAll(REFERENCE_PATTERN)) {
    if (match.index > at) {
      target.append(document.createTextNode(text.slice(at, match.index)));
    }
    const chip = document.createElement("span");
    chip.className = "ref";
    chip.textContent = `@${match[1]}:${decodeReferenceValue(match[2])}`;
    target.append(chip);
    at = match.index + match[0].length;
  }

  if (at < text.length) {
    target.append(document.createTextNode(text.slice(at)));
  }
}

pickerList.addEventListener("scroll", () => {
  const room = pickerList.scrollHeight - pickerList.scrollTop - pickerList.clientHeight;
  if (room < 40 && !pickerLoading && pickerItems.length < pickerTotal) {
    refreshPicker({ append: true });
  }
});

async function loadModels() {
  const response = await fetch("/api/models", {
    headers: { "x-scribe-token": TOKEN },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }

  const { models } = await response.json();
  modelSelect.replaceChildren();
  for (const model of models) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    modelSelect.append(option);
  }
  selectedModel = models[0] || "";
  modelSelect.value = selectedModel;
  modelLabel.textContent = selectedModel || "未配置模型";
}

function setModel(model) {
  if (!model) return;
  selectedModel = model;
  modelSelect.value = model;
  modelLabel.textContent = model;
}

modelSelect.addEventListener("change", () => {
  setModel(modelSelect.value);
});

function setSessionUrl(id) {
  const url = new URL(location.href);
  url.searchParams.set("session", id);
  history.replaceState(null, "", url);
}

function clearSessionUrl() {
  const url = new URL(location.href);
  url.searchParams.delete("session");
  history.replaceState(null, "", url);
}

function resetConversationView() {
  sessionId = null;
  bubbles = new Map();
  thinkings = new Map();
  toolCards = new Map();
  stream.replaceChildren();
}

function replayHistory(history) {
  resetConversationView();
  if (!history?.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.innerHTML = "<p>直接提问，或用下面的示例试试撰写能力。</p>";
    stream.append(empty);
    return;
  }

  for (const turn of history) {
    if (turn.prompt) {
      const mine = document.createElement("div");
      mine.className = "user";
      renderUserText(mine, turn.prompt);
      append(mine);
    }
    for (const event of turn.events || []) handle(event);
    flushRender();
  }
}

/** 模型可能把报告写进会话目录，一轮结束后重新拉清单才能看到产物。 */
async function refreshFiles() {
  if (!appSessionId) return;
  const response = await fetch(`/api/session/${appSessionId}`, {
    headers: { "x-scribe-token": TOKEN },
  });
  if (!response.ok) return;
  const session = await response.json();
  appFiles = session.files;
  renderFiles();
}

async function createAppSession() {
  appSessionReady = false;
  setBusy(false);
  fileStatus.textContent = "准备会话…";
  const response = await fetch("/api/session", {
    method: "POST",
    headers: { "x-scribe-token": TOKEN },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  const session = await response.json();
  appSessionId = session.appSessionId;
  appFiles = session.files;
  setModel(session.model || selectedModel);
  setSessionUrl(appSessionId);
  appSessionReady = true;
  renderFiles();
  setBusy(false);
}

async function restoreOrCreateSession() {
  const requestedId = new URL(location.href).searchParams.get("session");
  if (requestedId && /^[a-f0-9]{48}$/.test(requestedId)) {
    const response = await fetch(`/api/session/${requestedId}`, {
      headers: { "x-scribe-token": TOKEN },
    });
    if (response.ok) {
      const session = await response.json();
      appSessionId = session.appSessionId;
      appFiles = session.files;
      setModel(session.model || selectedModel);
      appSessionReady = true;
      renderFiles();
      replayHistory(session.history);
      sessionLabel.textContent = session.agentSessionId
        ? session.agentSessionId.slice(0, 8)
        : "";
      setBusy(false);
      return;
    }
  }

  clearSessionUrl();
  await createAppSession();
}

async function uploadFiles(files) {
  if (!appSessionReady || !files.length) return;
  fileStatus.textContent = "上传中…";
  fileInput.disabled = true;
  const body = new FormData();
  for (const file of files) body.append("files", file, file.name);

  try {
    const response = await fetch(`/api/session/${appSessionId}/files`, {
      method: "POST",
      headers: { "x-scribe-token": TOKEN },
      body,
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${await response.text()}`);
    }
    const session = await response.json();
    appFiles = session.files;
    renderFiles();
  } catch (error) {
    fileStatus.textContent = error.message;
  } finally {
    fileInput.value = "";
    fileInput.disabled = Boolean(controller) || !appSessionReady;
  }
}

fileInput.addEventListener("change", () => {
  uploadFiles([...fileInput.files]);
});

/**
 * 每个 scope（主线程或某个子代理）维护一个气泡。工具调用会打断气泡，
 * 之后的文本进入新气泡，保证时序和 CLI 一致。
 */
function bubbleFor(scope) {
  const existing = bubbles.get(scope);

  if (existing) {
    return existing;
  }

  const wrap = document.createElement("div");
  wrap.className = scope === "main" ? "assistant" : "assistant sub";

  const body = document.createElement("div");
  body.className = "md";
  wrap.append(body);
  append(wrap);

  const entry = { wrap, body, raw: "", dirty: false };
  bubbles.set(scope, entry);
  return entry;
}

// Markdown 全量重解析开销不小，用 rAF 合并同一帧内的多个增量。
let frame = null;

function flushRender() {
  if (frame !== null) {
    cancelAnimationFrame(frame);
    frame = null;
  }

  const stick = scrolledToBottom();

  for (const entry of bubbles.values()) {
    if (entry.dirty) {
      renderMarkdown(entry.body, entry.raw);
      entry.dirty = false;
    }
  }

  // 思考内容按纯文本写入：推理里常有半截的 markdown，解析会把结构搞乱。
  for (const entry of thinkings.values()) {
    if (entry.dirty) {
      entry.body.textContent = entry.raw;
      entry.label.textContent = `思考过程 · ${entry.raw.length} 字`;
      entry.dirty = false;
    }
  }

  if (stick) {
    stream.scrollTop = stream.scrollHeight;
  }
}

function scheduleRender() {
  if (frame === null) {
    frame = requestAnimationFrame(flushRender);
  }
}

function addText(scope, text) {
  clearEmpty();
  const entry = bubbleFor(scope);
  entry.raw += text;
  entry.dirty = true;
  scheduleRender();
}

/**
 * 思考块独立于正文气泡，绝不混进 .md，避免污染报告结构。
 * 一轮里 thinking 增量可达上千条，因此同样走 rAF 合并。
 */
function addThinking(scope, text) {
  const existing = thinkings.get(scope);

  if (existing) {
    existing.raw += text;
    existing.dirty = true;
    scheduleRender();
    return;
  }

  if (!text) {
    // 首个增量为空就不建块，否则流里会留下一个 0 字的空折叠框。
    return;
  }

  clearEmpty();
  const card = document.createElement("details");
  card.className = "thinking";

  const label = document.createElement("summary");
  const body = document.createElement("pre");
  card.append(label, body);
  append(card);

  const entry = { body, label, raw: text, dirty: true };
  thinkings.set(scope, entry);
  scheduleRender();
}

function addCard(className, label, detail, open = false) {
  clearEmpty();
  const card = document.createElement("details");
  card.className = className;
  card.open = open;

  const summary = document.createElement("summary");
  const strong = document.createElement("strong");
  strong.textContent = label;
  summary.append(strong);
  card.append(summary);

  if (detail) {
    const pre = document.createElement("pre");
    pre.textContent = detail;
    card.append(pre);
  }

  append(card);
  return summary;
}

function handle(event) {
  switch (event.type) {
    case "init": {
      sessionId = event.sessionId;
      modelLabel.textContent = event.model;
      sessionLabel.textContent = event.sessionId.slice(0, 8);
      capsLabel.textContent = [
        `${event.tools} 工具`,
        `${event.skills.length} Skills`,
        `${event.agents.length} 子代理`,
        `${event.commands.length} 命令`,
        event.mcpServers.length
          ? `MCP ${event.mcpServers.map((s) => `${s.name}:${s.status}`).join(",")}`
          : "无 MCP",
        event.permissionMode,
      ].join(" · ");
      return;
    }

    case "text":
      addText(event.scope, event.text);
      return;

    case "thinking":
      addThinking(event.scope, event.text);
      return;

    case "subagent": {
      clearEmpty();
      const head = document.createElement("div");
      head.className = "sub-head";
      head.textContent = `${event.subagentType}${
        event.description ? `：${event.description}` : ""
      }`;
      bubbleFor(event.scope).wrap.prepend(head);
      return;
    }

    case "tool_use": {
      // 移出 map 之后就再也刷不到这两个节点了，先同步刷一次，
      // 否则末尾增量会永远停在 raw 里，节点留着过期内容。
      flushRender();
      // 工具调用结束当前气泡和思考块，后续内容另起一段。
      bubbles.delete(event.scope);
      thinkings.delete(event.scope);
      const summary = addCard("card", event.name, event.input);
      const timer = document.createElement("span");
      timer.className = "muted";
      summary.append(timer);
      toolCards.set(event.id, timer);
      return;
    }

    case "tool_progress": {
      const timer = toolCards.get(event.id);
      if (timer && event.seconds > 0) {
        timer.textContent = `${event.seconds}s`;
      }
      return;
    }

    case "tool_result": {
      const timer = toolCards.get(event.id);
      if (timer) {
        timer.textContent = event.isError ? "失败" : "完成";
        if (event.isError) {
          timer.closest("details")?.classList.add("err");
        }
      }
      toolCards.delete(event.id);
      return;
    }

    case "activity": {
      clearEmpty();
      const line = document.createElement("div");
      line.className = "activity";
      line.textContent = `· ${event.label}${event.detail ? ` ${event.detail}` : ""}`;
      append(line);
      return;
    }

    case "result": {
      if (event.sessionId) {
        sessionId = event.sessionId;
        sessionLabel.textContent = event.sessionId.slice(0, 8);
      }

      const line = document.createElement("div");
      line.className = event.ok ? "result" : "result bad";
      const cost = event.costUsd ? ` · $${event.costUsd.toFixed(4)}` : "";
      line.textContent = event.ok
        ? `${event.turns} 轮 · ${(event.durationMs / 1000).toFixed(1)}s · ` +
          `${event.inputTokens} in / ${event.outputTokens} out${cost}`
        : event.message;
      append(line);
      return;
    }

    case "error": {
      const line = document.createElement("div");
      line.className = "result bad";
      line.textContent = event.message;
      append(line);
      return;
    }

    default:
      return;
  }
}

async function send(prompt) {
  clearEmpty();
  bubbles = new Map();
  thinkings = new Map();
  toolCards = new Map();

  const mine = document.createElement("div");
  mine.className = "user";
  renderUserText(mine, prompt);
  append(mine);

  controller = new AbortController();
  setBusy(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-scribe-token": TOKEN,
      },
      body: JSON.stringify({ prompt, sessionId, appSessionId, model: selectedModel }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`${response.status} ${await response.text()}`);
    }

    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";

    for (;;) {
      const { value, done } = await reader.read();

      if (done) {
        break;
      }

      buffer += value;
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const line = frame.split("\n").find((part) => part.startsWith("data: "));

        if (line) {
          handle(JSON.parse(line.slice(6)));
        }
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      handle({ type: "error", message: error.message });
    }
  } finally {
    // 标签页隐藏时 rAF 不触发，末尾增量会一直停在 raw 里。收尾同步刷一次，
    // 保证切走标签页期间结束的这一轮回来就是完整的，而不是空气泡。
    flushRender();
    controller = null;
    setBusy(false);
    input.focus();
    refreshFiles().catch(() => {});
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = input.value.trim();

  if (prompt && !controller) {
    input.value = "";
    closePicker();
    renderRefRow();
    send(prompt);
  }
});

input.addEventListener("keydown", (event) => {
  // 面板打开时方向键和回车归面板，否则回车会直接把半截查询词发出去。
  if (pickerOpen) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!pickerItems.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      pickerActive = (pickerActive + step + pickerItems.length) % pickerItems.length;
      renderPickerItems();
      pickerList.children[pickerActive]?.scrollIntoView({ block: "nearest" });
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      if (event.key === "Tab") {
        cycleSource(event.shiftKey ? -1 : 1);
        return;
      }
      const item = pickerItems[pickerActive];
      if (item) insertReference(item);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closePicker();
      return;
    }
  }

  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

input.addEventListener("input", () => {
  syncPicker();
  renderRefRow();
});

input.addEventListener("click", () => syncPicker());

input.addEventListener("blur", () => {
  // 延后关闭，让面板里的 mousedown 先跑完。
  setTimeout(() => {
    if (!picker.contains(document.activeElement)) closePicker();
  }, 0);
});

// 断开连接即触发服务端 request close，从而中止 query。
stopButton.addEventListener("click", () => controller?.abort());

const THINKING_KEY = "scribe.showThinking";

function applyThinkingPreference(on) {
  document.body.classList.toggle("show-thinking", on);
  thinkingToggle.checked = on;
}

thinkingToggle.addEventListener("change", () => {
  applyThinkingPreference(thinkingToggle.checked);
  localStorage.setItem(THINKING_KEY, thinkingToggle.checked ? "1" : "0");
});

// 默认关闭：思考内容对读报告的人是噪声，需要时再开。
applyThinkingPreference(localStorage.getItem(THINKING_KEY) === "1");

resetButton.addEventListener("click", () => {
  controller?.abort();
  appSessionReady = false;
  sessionId = null;
  bubbles = new Map();
  thinkings = new Map();
  toolCards = new Map();
  sessionLabel.textContent = "";
  stream.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.innerHTML = "<p>已开新会话。</p>";
  stream.append(empty);
  input.focus();
  createAppSession().catch((error) => {
    appSessionReady = false;
    setBusy(false);
    fileStatus.textContent = error.message;
  });
});

stream.addEventListener("click", (event) => {
  const prompt = event.target.closest("[data-prompt]")?.dataset.prompt;

  if (prompt && !controller) {
    send(prompt);
  }
});

Promise.all([loadModels(), loadSources()])
  .then(() => restoreOrCreateSession())
  .catch((error) => {
    appSessionReady = false;
    setBusy(false);
    fileStatus.textContent = `初始化失败：${error.message}`;
  });
