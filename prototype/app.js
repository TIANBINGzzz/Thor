"use strict";
const enhanced = document.body.dataset.mode !== "original";
const svg = (name, className = "") => {
  const paths = {
    folder: '<path d="M2 5h6l2 2h8v10H2z"/>',
    plus: '<path d="M10 3v14M3 10h14"/>',
    chevron: '<path d="m7 4 6 6-6 6"/>',
    close: '<path d="m5 5 10 10M15 5 5 15"/>',
    stop: '<rect x="5" y="5" width="10" height="10" rx="1"/>',
    file: '<path d="M4 2h8l4 4v12H4zM12 2v5h4M7 10h6M7 13h6"/>',
    chart: '<path d="M3 3v14h14M7 13V9m4 4V5m4 8V8"/>',
    pencil: '<path d="m4 13 9-9 3 3-9 9-4 1zM11 6l3 3"/>',
    settings: '<circle cx="10" cy="10" r="3"/><path d="M10 2v2m0 12v2M2 10h2m12 0h2M4.3 4.3l1.4 1.4m8.6 8.6 1.4 1.4M4.3 15.7l1.4-1.4m8.6-8.6 1.4-1.4"/>',
    down: '<path d="M10 3v14m-5-5 5 5 5-5"/>'
  };
  return `<svg viewBox="0 0 20 20" class="icon ${className}" aria-hidden="true">${paths[name] || paths.file}</svg>`;
};
document.querySelector('#app').innerHTML = `
<div class="ai-theme-root"><div class="ai-layout" id="layout">
  <aside class="ai-layout__sidebar" aria-label="主导航">
    <div class="ai-sidebar" id="sidebar">
      <div class="user-profile">
        <div class="user-profile__brand"><div class="user-profile__logo"><img class="user-profile__logo-img" src="assets/ai-icon.png" alt=""></div><span class="user-profile__title">AI 师创智能体</span></div>
        <button class="user-profile__toggle" id="collapseSidebar" aria-label="收起侧边栏" title="收起侧边栏"><img class="user-profile__toggle-img" src="assets/left.png" alt=""></button>
      </div>
      <nav class="sidebar-actions">
        <button class="sidebar-actions__item" id="newChatButton" title="新对话"><img src="assets/add.png" class="sidebar-actions__item-img" alt=""><span>新对话</span></button>
        <button class="sidebar-actions__item" id="libraryButton" title="文件库">${svg('folder', 'sidebar-actions__item-icon')}<span>文件库</span></button>
        <button class="sidebar-actions__item" id="marketButton" title="智能体市场"><img src="assets/list.png" class="sidebar-actions__item-img" alt=""><span>智能体市场</span></button>
      </nav>
      <div class="ai-sidebar__history">
        <div class="session-search"><div class="session-search__title">历史会话</div><div class="session-search__field"><input id="sessionSearch" aria-label="搜索历史会话" placeholder="搜索历史会话"><img src="assets/search.png" class="session-search__icon" alt=""></div></div>
        <div class="ai-sidebar__history-scroll"><div id="sessionList"></div></div>
      </div>
      <div class="sidebar-user-footer"><div class="sidebar-user-info"><button class="sidebar-user-info__trigger sidebar-user-info__trigger--full" id="profileButton" aria-label="演示用户"><span class="demo-avatar">陈</span><div class="sidebar-user-info__meta"><div class="sidebar-user-info__name">陈老师</div><div class="sidebar-user-info__org">演示学校</div></div><img src="assets/down.png" class="sidebar-user-info__arrow" alt=""></button></div></div>
    </div>
  </aside>
  <main class="ai-layout__main"><div class="ai-layout__main-inner"><div class="chat-panel">
    <header class="chat-header"><button class="chat-header__toggle" id="expandSidebar" aria-label="展开侧边栏" title="展开侧边栏" hidden><img src="assets/right.png" class="chat-header__toggle-img" alt=""></button><h1 id="chatTitle" class="chat-header__title"></h1></header>
    <div class="chat-panel__body-wrap">
      <div class="chat-panel__body" id="chatScroll">
        <div class="topic-welcome-card"><div class="topic-welcome-card__card">
          <div class="topic-welcome-card__header"><div class="topic-welcome-card__avatar"><img src="assets/robot.png" class="topic-welcome-card__avatar-img" alt="师创智能体"></div><div class="topic-welcome-card__intro"><div class="topic-welcome-card__title">你好，我是 师创智能体</div><div class="topic-welcome-card__desc">你好，我是 AI 助手，请问有什么可以帮助你的？</div></div></div>
          <div class="suggestion-chips" id="suggestions" hidden><div class="suggestion-chips__header"><span class="suggestion-chips__label">你可以试着问我</span></div><div class="suggestion-chips__grid"><button class="suggestion-chips__item">总结近期建设项目的主要进展</button><button class="suggestion-chips__item">对比学校各年度建设目标</button><button class="suggestion-chips__item">把年度结论整理成正式简报</button></div></div>
        </div></div>
        <div class="message-list" id="messageList"></div>
      </div>
      <div class="chat-panel__bottom-floats" id="bottomFloat" hidden><button class="queue-remove" id="scrollBottom" title="回到最新消息" aria-label="回到最新消息">${svg('down')}</button></div>
    </div>
    <div class="chat-input-bar"><div class="chat-input-bar__wrapper">
      <section class="queue" id="queueSection" aria-label="等待处理的消息" hidden><div class="queue-heading"><strong>待处理 <span id="queueBadge"></span></strong><span>按发送顺序处理</span></div><div class="queue-items" id="queueItems"></div></section>
      <div class="input-popover" id="inputMenu" hidden><button type="button" data-upload="file"><img src="assets/import-file.svg" alt="">上传文档</button><button type="button" data-upload="image"><img src="assets/import-img.svg" alt="">上传图片</button><hr><button type="button" data-capability="校双高综合咨询">${svg('chart')}校双高综合咨询</button><button type="button" data-capability="文稿撰写">${svg('pencil')}文稿撰写</button><button type="button" data-capability="政策问答">${svg('file')}政策问答</button></div>
      <form id="composerForm" class="chat-input-bar__content">
        <button type="button" class="chat-input-bar__template-btn" id="templateButton" hidden>${svg('file')}<span>选择模版</span></button>
        <div id="draftAttachments" class="attachment-list" hidden></div>
        <textarea id="messageInput" class="chat-input-bar__textarea ant-input" aria-label="输入消息" placeholder="在此输入您想了解或办理的内容..." rows="2" maxlength="4000"></textarea>
        <div class="chat-input-bar__box">
          <button type="button" class="chat-input-bar__tool_small" id="addButton" aria-label="添加" title="添加" aria-expanded="false">${svg('plus')}</button>
          <div id="capabilityTag" class="selected-capability" hidden>${svg('chart')}<span id="capabilityName"></span><button type="button" id="clearCapability" aria-label="取消所选能力" title="取消">${svg('close')}</button></div>
          <div class="chat-input-bar__actions"><button type="button" class="chat-input-bar__voice" id="voiceButton" aria-label="点击开始语音输入" title="点击开始语音输入"><svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36"><rect fill="currentColor" width="36" height="36" rx="18"/><path fill="#333" d="M9.558,2.454A2.181,2.181,0,0,0,7.377,4.635V7.543a2.181,2.181,0,0,0,4.362,0V4.635A2.181,2.181,0,0,0,9.558,2.454ZM9.558,1a3.635,3.635,0,0,1,3.635,3.635V7.543a3.635,3.635,0,0,1-7.27,0V4.635A3.635,3.635,0,0,1,9.558,1Zm-6.5,7.27H4.52a5.09,5.09,0,0,0,10.076,0h1.466a6.546,6.546,0,0,1-5.776,5.776V17H8.831V14.047A6.546,6.546,0,0,1,3.055,8.27Z" transform="translate(8.442 9.002)"/></svg></button><button type="button" class="chat-input-bar__send chat-input-bar__send--stop" id="stopRunButton" aria-label="停止生成" title="停止生成" hidden>${svg('stop')}</button><button type="submit" class="chat-input-bar__send" id="sendButton" aria-label="发送" title="发送" disabled><svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36"><rect fill="currentColor" width="36" height="36" rx="18"/><path fill="#fff" d="M13,7.828V20H11V7.828L5.636,13.192,4.222,11.778,12,4l7.778,7.778-1.414,1.414Z" transform="translate(6.152 5)"/></svg></button></div>
        </div>
      </form>
      <p class="chat-input-bar__disclaimer">AI 输出仅供参考，请以系统数据、业务规则及人工复核结果为准。</p>
      <input type="file" id="fileInput" multiple hidden>
    </div></div>
  </div></div></main>
</div></div>
<details class="prototype-controls" id="demoControls"><summary aria-label="原型演示" title="原型演示">${svg('settings')}</summary><div class="prototype-menu"><p>${enhanced ? '功能增强版' : '原页面还原版'} · 本地模拟</p><a href="${enhanced ? 'original.html' : 'index.html'}">${enhanced ? '查看原页面还原版' : '查看功能增强版'}</a><button data-demo="reset">重新开始演示</button><button data-demo="complete">完成当前运行</button><button data-demo="fail">模拟运行失败</button><button data-demo="welcome">查看新对话</button></div></details>
<dialog id="dialog"><form method="dialog" id="dialogForm"><h2 id="dialogTitle"></h2><div id="dialogContent"></div><div class="dialog-actions"><button value="cancel">关闭</button><button class="primary" id="dialogSave" value="save" hidden>保存</button></div></form></dialog>
<div id="announcement" class="notice" role="status" aria-live="polite" hidden></div>`;



    // 只模拟业务会话与公开 SSE；不调用 Runtime、模型或私有观测接口。
    // 信封与显示规则来源：python/runtime/event_display.py、run_store.py、doc/python-api.html。
    const $ = selector => document.querySelector(selector);
    const pad = value => String(value).padStart(2, "0");
    const duration = ms => {
      const seconds = Math.max(0, Math.floor(ms / 1000));
      return (seconds >= 3600 ? pad(Math.floor(seconds / 3600)) + ":" : "") +
        pad(Math.floor(seconds / 60) % 60) + ":" + pad(seconds % 60);
    };
    const setText = (selector, value) => { $(selector).textContent = value; };
    const terminal = run => ["completed", "cancelled", "failed"].includes(run.status);
    const storageKey = enhanced ? "scribe-prototype-enhanced-v3" : "scribe-prototype-original-v1";
    const phaseNames = {
      queued: "等待处理", preparing_files: "正在准备附件", files_ready: "",
      model_starting: "正在处理", thinking: "正在思考", saving_files: "正在保存文件"
    };
    const eventNames = {
      "run.started": "正在处理", "run.completed": "已完成", "run.failed": "执行失败",
      "run.cancelled": "已停止", "message.delta": "", "artifact.pending": "等待上传",
      "artifact.uploading": "正在上传", "artifact.ready": "文件已保存"
    };
    const toolNames = { "data.query": "查询业务数据", "document.process": "处理文档" };
    const statusNames = { queued: "排队中", running: "正在运行", completed: "已完成", cancelled: "已停止", failed: "执行失败" };
    let store = { sessions: [], currentId: "" };
    let composing = false;

    const current = () => store.sessions.find(session => session.id === store.currentId);
    const active = session => session.runs.find(run => run.runId === session.activeId);
    const element = (tag, className, value) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (value !== undefined) node.textContent = value;
      return node;
    };
    function button(label, className, handler) {
      const node = element("button", className, label);
      node.type = "button";
      node.addEventListener("click", handler);
      return node;
    }
    let noticeTimer;
    function announce(message) {
      setText("#announcement", message);
      $("#announcement").hidden = false;
      clearTimeout(noticeTimer);
      noticeTimer = setTimeout(() => { $("#announcement").hidden = true; }, 2600);
    }
    function save() {
      try { localStorage.setItem(storageKey, JSON.stringify(store)); }
      catch { announce("浏览器存储不可用，记录只保留在当前页面。"); }
    }
    function newSession(title) {
      const session = {
        id: "session_" + crypto.randomUUID(), title, runs: [],
        queue: [], activeId: null
      };
      store.sessions.push(session);
      store.currentId = session.id;
      return session;
    }

    // 所有消息正文由 message.delta 追加；空 displayName 不补造工具/阶段状态。
    // 按 Run 独立去重并按 sequence 回看。公开工具名称不会包含内部 toolName/参数/结果。
    function append(run, type, payload = {}, occurredAt = Date.now()) {
      const sequence = run.events.length + 1;
      const displayName = type === "phase" ? phaseNames[payload.name] ?? "" :
        type.startsWith("tool.") ? toolNames[payload.toolKey] ?? "" : eventNames[type] ?? "";
      const event = {
        protocolVersion: "agent-events/v1", runId: run.runId, sequence,
        eventId: "evt_" + run.shortId + "_" + pad(sequence),
        occurredAt, type, payload: { ...payload, displayName }
      };
      if (run.events.some(item => item.eventId === event.eventId || item.sequence === sequence)) return;
      run.events.push(event);
      if (type === "message.delta") run.answer += payload.textDelta;
      if (type.startsWith("artifact.")) run.artifact = { ...payload, displayName };
    }

    function scenario(prompt) {
      if (/简报|正式|文档/.test(prompt)) return {
        kind: "document", toolKey: "document.process",
        chunks: [
          "我会沿用前面的年度对比结论，按“总体进展—阶段成果—后续关注项”的结构整理简报。\n\n",
          "示例简报已整理完成。正式使用时，需继续核验数据来源、统计口径与文稿内容。"
        ],
        artifact: "双高建设年度进展简报.pdf"
      };
      if (/学院|差异/.test(prompt)) return {
        kind: "query", toolKey: "data.query",
        chunks: [
          "本轮将按二级学院归纳完成情况，并将统计口径不一致的指标单独标记。\n\n",
          "示例分析已整理：对比时应同时查看任务完成进度、年度目标与证据完整性，不直接用不同口径的数值排序。"
        ]
      };
      if (/2023|2025|年度|目标/.test(prompt)) return {
        kind: "query", toolKey: "data.query",
        chunks: [
          "我会按年度对齐建设目标、统计口径和成果证据，再整理三年的进展变化。\n\n",
          "示例对比已完成：先概括各年的阶段成果，再列出延续任务与需要补充证据的指标。"
        ]
      };
      return {
        kind: "query", toolKey: "data.query",
        chunks: [
          "已开始处理这条消息。\n\n",
          "这是本地原型的示例回复，用于体验串行执行、停止、计时和事件回看；实际内容将在接入服务后生成。"
        ]
      };
    }
    function makeRun(prompt, submittedAt) {
      const id = crypto.randomUUID().replaceAll("-", "").slice(0, 10);
      const run = {
        runId: "run_" + id, shortId: id, prompt, submittedAt, startedAt: null,
        endedAt: null, status: "queued", events: [], answer: "", cursor: 0,
        scenario: scenario(prompt), artifact: null, expanded: false
      };
      // Python Client 实现先发 run.started，再发 phase.queued；不能把前者当作已开始模型执行。
      append(run, "run.started", { status: "running" }, submittedAt);
      append(run, "phase", { name: "queued" }, submittedAt + 1);
      return run;
    }
    function steps(run) {
      const type = run.scenario.toolKey;
      const call = { toolCallId: "call_" + run.shortId, toolKey: type, scope: "main" };
      const result = [
        [1200, "phase", { name: "thinking", visible: true }],
        [4500, "tool.started", { ...call, status: "started" }],
        [12500, "tool.progress", { ...call, status: "running" }],
        [21000, "tool.finished", { ...call, status: "finished", isError: false }],
        [24500, "phase", { name: "thinking", visible: true }],
        [28000, "message.delta", { textDelta: run.scenario.chunks[0] }],
        [35000, "message.delta", { textDelta: run.scenario.chunks[1] }]
      ];
      if (run.scenario.artifact) {
        const file = { artifactId: "artifact_" + run.shortId, name: run.scenario.artifact, size: 68420, suffix: "pdf" };
        result.push(
          [37000, "artifact.pending", { ...file, status: "pending" }],
          [38500, "phase", { name: "saving_files" }],
          [39500, "artifact.uploading", { ...file, status: "uploading" }],
          [43000, "artifact.ready", { ...file, fileId: "file_demo_" + run.shortId, status: "ready" }]
        );
      }
      return result;
    }

    function startNext(session, now = Date.now()) {
      if (active(session) || !session.queue.length) return;
      const runId = session.queue.shift();
      const run = session.runs.find(item => item.runId === runId);
      run.status = "running";
      run.startedAt = now;
      session.activeId = run.runId;
      // 原型的“已处理”从首个执行阶段计时；排队时间另算，不读取私有 Timing。
      append(run, "phase", { name: "model_starting" }, now);
    }
    function enqueue(session, prompt, now = Date.now()) {
      const run = makeRun(prompt, now);
      session.runs.push(run);
      session.queue.push(run.runId);
      if (session.title === "新对话") session.title = prompt.slice(0, 24);
      startNext(session, now + 2);
      return run;
    }
    function advance(run, now) {
      const script = steps(run);
      while (run.cursor < script.length && now >= run.startedAt + script[run.cursor][0]) {
        const [offset, type, payload] = script[run.cursor++];
        append(run, type, payload, run.startedAt + offset);
      }
    }
    function finish(session, run, status, now = Date.now()) {
      if (terminal(run)) return;
      run.status = status;
      run.endedAt = now;
      run.expanded = false;
      append(run, "run." + status, status === "failed" ?
        { code: "timeout", message: "本次处理超时，请稍后重试。" } : {}, now);
      session.queue = session.queue.filter(id => id !== run.runId);
      if (session.activeId === run.runId) session.activeId = null;
      // 完成、失败、停止均释放当前会话，下一条只在终态之后进入执行阶段。
      startNext(session, now + 2);
      save();
    }
    function cancelQueued(runId) {
      const session = current();
      const run = session.runs.find(item => item.runId === runId);
      if (!run || run.status !== "queued") return;
      finish(session, run, "cancelled");
      refresh();
      announce("已取消这条排队消息。");
    }
    function tick() {
      let changed = false;
      const now = Date.now();
      store.sessions.forEach(session => {
        const run = active(session);
        if (!run) return;
        const before = run.events.length;
        advance(run, now);
        if (now >= run.startedAt + 45000) finish(session, run, "completed", run.startedAt + 45000);
        changed ||= before !== run.events.length;
      });
      if (changed) { save(); refresh(); }
      updateClocks();
    }

    function seedDemo() {
      store = { sessions: [], currentId: "" };
      const now = Date.now();
      for (const name of ["年度工作总结", "文稿格式与材料整理", "学校建设项目咨询"]) newSession(name);
      const session = newSession("校双高建设进展分析");
      const previous = enqueue(session, "总结近期建设项目的主要进展。", now - 180000);
      previous.scenario.chunks = [
        "我会从目标进度、阶段成果和后续关注项三个方面梳理。\n\n",
        "可以继续指定年度或学院范围，我会在当前会话中衔接分析。"
      ];
      advance(previous, previous.startedAt + 45000);
      finish(session, previous, "completed", previous.startedAt + 45000);
      const live = enqueue(session, "请对比学校2023—2025年双高建设目标完成情况，提炼年度进展。", now - 8000);
      advance(live, now);
      if (enhanced) {
        enqueue(session, "再看一下校内各二级学院的完成情况，标出差异较大的指标。", now - 5500);
        enqueue(session, "请把年度对比结论整理成一份正式简报。", now - 2200);
      }
      save();
      refresh(true);
    }
    function restore() {
      try {
        const data = JSON.parse(localStorage.getItem(storageKey));
        if (!data || !Array.isArray(data.sessions) || !data.sessions.length ||
            !data.sessions.every(session => Array.isArray(session.runs) && Array.isArray(session.queue)) ||
            !data.sessions.some(session => session.id === data.currentId)) return false;
        store = data;
        // 恢复本地模拟状态；原始事件时间戳不改写，由 tick 推进尚未完成的演示。
        return true;
      } catch { return false; }
    }

    function currentActivity(run) {
      if (terminal(run)) return statusNames[run.status];
      if (!run.startedAt) return "等待处理";
      const calls = new Map();
      for (const event of run.events) {
        if (event.type.startsWith("tool.")) calls.set(event.payload.scope + ":" + event.payload.toolCallId, event);
      }
      const executing = Array.from(calls.values()).find(event =>
        event.type !== "tool.finished" && event.payload.displayName);
      if (executing) return executing.payload.displayName;
      return run.events.slice().reverse().find(event =>
        event.type === "phase" && event.payload.displayName && event.payload.name !== "queued")?.payload.displayName || "正在处理";
    }
    function humanDuration(ms) {
      const seconds = Math.max(0, Math.floor(ms / 1000));
      return Math.floor(seconds / 3600) + "小时" + pad(Math.floor(seconds / 60) % 60) + "分" + pad(seconds % 60) + "秒";
    }

    let draftFiles = [];
    let selectedCapability = "";
    let collapsed = window.matchMedia('(max-width: 650px)').matches;
    let dialogSave = null;
    const iconButton = (label, iconName, handler, className) => {
      const node = button("", className || "message-footer__icon", handler);
      node.title = label;
      node.setAttribute('aria-label', label);
      if (iconName.endsWith('.png')) {
        const img = element('img', 'message-footer__icon-img');
        img.src = 'assets/' + iconName; img.alt = '';
        node.append(img);
      } else node.innerHTML = svg(iconName);
      return node;
    };
    function dots(node) {
      for (let i = 0; i < 3; i++) node.append(element('span', 'agent-message__dot'));
    }
    function renderMessages() {
      const list = $('#messageList');
      list.replaceChildren();
      const runs = current().runs.filter(run => run.startedAt !== null || terminal(run));
      $('#suggestions').hidden = runs.length > 0;
      for (const run of runs) {
        const turn = element('section', 'turn');
        turn.dataset.run = run.runId;
        const user = element('div', 'user-message');
        const userContent = element('div', 'user-message__content');
        if (run.attachments?.length) {
          const attachments = element('div', 'attachment-list');
          for (const file of run.attachments) attachments.append(fileChip(file.name));
          userContent.append(attachments);
        }
        userContent.append(element('div', 'user-message__bubble', run.prompt));
        user.append(userContent);
        const assistant = element('article', 'agent-message');
        const bubble = element('div', 'agent-message__bubble');
        if (enhanced) {
          const clock = element('div', 'runtime-clock');
          clock.dataset.clockRun = run.runId;
          const process = element('details', 'runtime-process' + (terminal(run) ? '' : ' is-running'));
          process.open = !terminal(run) || run.expanded === true;
          const summary = element('summary');
          summary.append(element('span', 'agent-message__thinking-text', currentActivity(run)));
          if (!terminal(run)) dots(summary);
          else summary.insertAdjacentHTML('beforeend', svg('chevron', 'chevron'));
          summary.addEventListener('click', event => { if (!terminal(run)) event.preventDefault(); });
          process.addEventListener('toggle', () => {
            if (process.isConnected && terminal(run)) { run.expanded = process.open; save(); }
          });
          const timeline = element('ol', 'runtime-timeline');
          timeline.setAttribute('aria-label', '处理过程');
          const visible = run.events.filter(event => event.payload.displayName);
          // 只使用公共 displayName；空标题不补造，不渲染 Run ID、参数或结果详情。
          visible.forEach((event, index) => {
            timeline.append(element('li', 'runtime-node' + (!terminal(run) && index === visible.length - 1 ? ' is-current' : ''), event.payload.displayName));
          });
          process.append(summary, timeline);
          bubble.append(clock, process);
        } else if (!terminal(run)) {
          const activity = element('div', 'agent-message__thinking');
          activity.append(element('span', 'agent-message__thinking-text', currentActivity(run)));
          dots(activity); bubble.append(activity);
        }
        if (run.answer && (!enhanced || terminal(run))) {
          const content = element('div', 'agent-message__text');
          content.append(element('div', 'agent-message__markdown', run.answer));
          bubble.append(content);
        }
        if (run.status === 'cancelled' || run.status === 'failed') {
          bubble.append(element('div', 'terminal-note', run.status === 'failed' ? '本次处理未完成，可以重新回答。' : run.startedAt ? '已停止生成，可点击下方「重新回答」再试一次' : '已取消排队'));
        }
        if (terminal(run) && run.artifact) bubble.append(fileChip(run.artifact.name));
        assistant.append(bubble);
        if (terminal(run)) {
          const footer = element('div', 'message-footer');
          const toolbar = element('div', 'message-footer__toolbar');
          toolbar.append(iconButton('复制', 'fz.png', async () => {
            try { await navigator.clipboard.writeText(run.answer); announce('已复制'); }
            catch { announce('复制未成功，请选中正文后复制。'); }
          }));
          toolbar.append(iconButton('重新回答', 'cxhd.png', () => { submitPrompt(run.prompt, run.attachments || []); }));
          for (const [kind, label, asset, selected] of [['like', '点赞', 'dz.png', 'dzl.png'], ['dislike', '点踩', 'dc.png', 'dcl.png']]) {
            const btn = iconButton(label, run.feedback === kind ? selected : asset, () => {
              run.feedback = run.feedback === kind ? null : kind; save(); renderMessages();
            });
            btn.setAttribute('aria-pressed', String(run.feedback === kind)); toolbar.append(btn);
          }
          footer.append(toolbar); assistant.append(footer);
        }
        turn.append(user, assistant); list.append(turn);
      }
    }
    function fileChip(name) {
      const chip = element('div', 'attachment-chip');
      const image = element('img'); image.src = 'assets/word-icon.png'; image.alt = '';
      chip.append(image, element('span', '', name));
      return chip;
    }
    function renderQueue() {
      const session = current();
      const list = $('#queueItems'); list.replaceChildren();
      $('#queueSection').hidden = !enhanced || !session.queue.length;
      setText('#queueBadge', String(session.queue.length));
      for (const [index, id] of session.queue.entries()) {
        const run = session.runs.find(item => item.runId === id);
        const row = element('div', 'queue-row');
        row.append(element('span', 'queue-number', pad(index + 1)));
        const content = element('div', 'queue-content');
        content.append(element('div', 'queue-title', run.prompt));
        const hint = element('div', 'queue-hint'); hint.dataset.queueRun = id;
        hint.append(element('span', '', index ? '等待中 · ' : '下一条 · '), element('span', 'queue-wait'), element('span', '', ' 已排队'));
        content.append(hint); row.append(content);
        row.append(iconButton('取消队列第 ' + (index + 1) + ' 条消息', 'close', () => cancelQueued(id), 'queue-remove'));
        list.append(row);
      }
    }
    function renderSessions() {
      setText('#chatTitle', current().title === '新对话' ? '师创智能体' : current().title);
      const list = $('#sessionList'); list.replaceChildren();
      const keyword = $('#sessionSearch').value.trim();
      for (const session of store.sessions.slice().reverse().filter(item => item.title.includes(keyword))) {
        const row = element('div', 'session-item' + (session.id === store.currentId ? ' session-item--active' : ''));
        const select = button('', 'session-item__select', () => {
          current().draft = $('#messageInput').value; store.currentId = session.id;
          $('#messageInput').value = session.draft || ''; draftFiles = []; renderDraft(); save(); refresh(true);
        });
        select.title = session.title;
        const icon = element('span', 'session-item__icon');
        const img = element('img', 'session-item__icon-img'); img.src = 'assets/ai-icon.png'; img.alt = '';
        icon.append(img); select.append(icon, element('span', 'session-item__title', session.title));
        const more = button('', 'session-item__more', () => renameSession(session));
        more.setAttribute('aria-label', '重命名会话：' + session.title); more.title = '重命名会话';
        const menuImg = element('img'); menuImg.src = 'assets/more.png'; menuImg.alt = ''; more.append(menuImg);
        row.append(select, more); list.append(row);
      }
      $('#newChatButton').classList.toggle('sidebar-actions__item--active', !current().runs.length);
    }
    function updateClocks() {
      const session = current(); const running = active(session); const now = Date.now();
      $('#stopRunButton').hidden = !running;
      // 原页面保留停止按钮行为；增强版在处理期间同时允许继续发送并进入队列。
      $('#sendButton').hidden = !enhanced && !!running;
      $('#sendButton').disabled = !$('#messageInput').value.trim() && !draftFiles.length;
      const label = enhanced && running ? '加入队列' : '发送';
      $('#sendButton').setAttribute('aria-label', label); $('#sendButton').title = label;
      document.querySelectorAll('[data-clock-run]').forEach(node => {
        const run = session.runs.find(item => item.runId === node.dataset.clockRun);
        node.textContent = (run.startedAt ? '已处理 ' : '已等待 ') + humanDuration((run.endedAt || now) - (run.startedAt || run.submittedAt));
      });
      document.querySelectorAll('[data-queue-run]').forEach(node => {
        const run = session.runs.find(item => item.runId === node.dataset.queueRun);
        node.querySelector('.queue-wait').textContent = duration(now - run.submittedAt);
      });
    }
    function refresh(bottom = false) {
      const scroller = $('#chatScroll');
      const nearBottom = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop < 80;
      const oldTop = scroller.scrollTop;
      renderSessions(); renderMessages(); renderQueue(); updateClocks();
      scroller.scrollTop = bottom || nearBottom ? scroller.scrollHeight : oldTop;
      $('#bottomFloat').hidden = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop < 120;
    }
    function submitPrompt(prompt, files = []) {
      if (!prompt.trim() && !files.length) return;
      if (!enhanced && active(current())) { announce('当前正在生成，请完成后再发送。'); return; }
      const wasRunning = !!active(current());
      const run = enqueue(current(), prompt.trim() || '请阅读附件。');
      run.attachments = files; run.capability = selectedCapability;
      save(); refresh(true);
      if (wasRunning) announce('已加入队列，当前处理结束后按顺序执行。');
    }
    function newChat() {
      current().draft = $('#messageInput').value;
      newSession('新对话'); $('#messageInput').value = ''; draftFiles = []; renderDraft();
      save(); refresh(true); $('#messageInput').focus();
    }
    function setSidebar(value) {
      collapsed = value;
      $('#layout').classList.toggle('ai-layout--collapsed', value);
      $('#sidebar').classList.toggle('is-collapsed', value);
      $('#expandSidebar').hidden = !value;
      $('#layout').classList.toggle('mobile-sidebar-open', !value && matchMedia('(max-width: 650px)').matches);
    }
    function showDialog(title, content, saveHandler) {
      setText('#dialogTitle', title); $('#dialogContent').replaceChildren(content);
      $('#dialogSave').hidden = !saveHandler; dialogSave = saveHandler;
      $('#dialog').showModal();
    }
    function renameSession(session) {
      const input = element('input'); input.value = session.title; input.maxLength = 60;
      input.setAttribute('aria-label', '会话名称');
      showDialog('重命名会话', input, () => { if (input.value.trim()) { session.title = input.value.trim(); save(); renderSessions(); } });
    }
    function closeInputMenu() { $('#inputMenu').hidden = true; $('#addButton').setAttribute('aria-expanded', 'false'); }
    function selectCapability(name) {
      selectedCapability = name; setText('#capabilityName', name); $('#capabilityTag').hidden = !name;
      $('#templateButton').hidden = name !== '文稿撰写'; closeInputMenu();
    }
    function renderDraft() {
      const list = $('#draftAttachments'); list.replaceChildren(); list.hidden = !draftFiles.length;
      draftFiles.forEach((file, index) => {
        const chip = fileChip(file.name);
        chip.append(iconButton('移除附件：' + file.name, 'close', () => { draftFiles.splice(index, 1); renderDraft(); updateClocks(); }, 'queue-remove'));
        list.append(chip);
      });
    }
    $('#composerForm').addEventListener('submit', event => {
      event.preventDefault(); if (composing || (!enhanced && active(current()))) return;
      const input = $('#messageInput'); const text = input.value;
      if (!text.trim() && !draftFiles.length) return;
      input.value = ''; input.style.height = ''; current().draft = '';
      const files = draftFiles; draftFiles = []; renderDraft(); submitPrompt(text, files);
    });
    $('#messageInput').addEventListener('input', () => {
      const input = $('#messageInput'); input.style.height = '55px'; input.style.height = Math.min(input.scrollHeight, 132) + 'px'; updateClocks();
    });
    $('#messageInput').addEventListener('compositionstart', () => { composing = true; });
    $('#messageInput').addEventListener('compositionend', () => { composing = false; });
    $('#messageInput').addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing && event.keyCode !== 229) { event.preventDefault(); $('#composerForm').requestSubmit(); }
    });
    $('#newChatButton').addEventListener('click', newChat);
    $('#sessionSearch').addEventListener('input', renderSessions);
    $('#collapseSidebar').addEventListener('click', () => setSidebar(true));
    $('#expandSidebar').addEventListener('click', () => setSidebar(false));
    $('#stopRunButton').addEventListener('click', () => { const run = active(current()); if (run) { finish(current(), run, 'cancelled'); refresh(); } });
    $('#chatScroll').addEventListener('scroll', () => { const scroller = $('#chatScroll'); $('#bottomFloat').hidden = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop < 120; });
    $('#scrollBottom').addEventListener('click', () => { $('#chatScroll').scrollTop = $('#chatScroll').scrollHeight; });
    $('#addButton').addEventListener('click', () => { $('#inputMenu').hidden = !$('#inputMenu').hidden; $('#addButton').setAttribute('aria-expanded', String(!$('#inputMenu').hidden)); });
    document.addEventListener('click', event => { if (!event.target.closest('#inputMenu, #addButton')) closeInputMenu(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeInputMenu(); $('#demoControls').open = false; } });
    document.querySelectorAll('[data-capability]').forEach(node => node.addEventListener('click', () => selectCapability(node.dataset.capability)));
    $('#clearCapability').addEventListener('click', () => selectCapability(''));
    document.querySelectorAll('[data-upload]').forEach(node => node.addEventListener('click', () => {
      $('#fileInput').accept = node.dataset.upload === 'image' ? 'image/*' : '.pdf,.doc,.docx,.txt,.xls,.xlsx,.csv';
      $('#fileInput').click(); closeInputMenu();
    }));
    $('#fileInput').addEventListener('change', event => {
      draftFiles.push(...Array.from(event.target.files).map(file => ({name: file.name, size: file.size, type: file.type})));
      event.target.value = ''; renderDraft(); updateClocks(); announce('已添加附件名称，本地原型不会上传文件。');
    });
    $('#voiceButton').addEventListener('click', () => announce('语音入口已还原，本地原型暂不录音。'));
    $('#profileButton').addEventListener('click', () => showDialog('陈老师 · 演示学校', element('p', '', '当前为本地原型，使用演示身份与模拟消息。')));
    $('#libraryButton').addEventListener('click', () => {
      const list = element('div', 'dialog-list');
      const files = current().runs.flatMap(run => [...(run.attachments || []), ...(run.artifact ? [run.artifact] : [])]);
      if (!files.length) list.append(element('p', '', '暂无文件。可从输入框的「添加」入口选择本地附件。'));
      for (const file of files) list.append(fileChip(file.name));
      showDialog('文件库', list);
    });
    $('#marketButton').addEventListener('click', () => {
      const list = element('div', 'dialog-list');
      for (const name of ['校双高综合咨询', '文稿撰写', '政策问答']) list.append(button(name, '', () => { selectCapability(name); $('#dialog').close(); }));
      showDialog('智能体市场', list);
    });
    $('#templateButton').addEventListener('click', () => {
      const list = element('div', 'dialog-list');
      for (const name of ['年度工作简报', '建设进展总结']) list.append(button(name, '', () => { draftFiles.push({name: name + '.docx', template: true}); renderDraft(); updateClocks(); $('#dialog').close(); }));
      showDialog('选择模版', list);
    });
    $('#dialog').addEventListener('close', () => { if ($('#dialog').returnValue === 'save') dialogSave?.(); dialogSave = null; });
    document.querySelectorAll('.suggestion-chips__item').forEach(node => node.addEventListener('click', () => submitPrompt(node.textContent)));
    document.querySelectorAll('[data-demo]').forEach(node => node.addEventListener('click', () => {
      $('#demoControls').open = false;
      const action = node.dataset.demo;
      if (action === 'welcome') { newChat(); return; }
      if (action === 'reset') { $('#sessionSearch').value = ''; $('#messageInput').value = ''; draftFiles = []; renderDraft(); seedDemo(); return; }
      const run = active(current()); if (!run) { announce('当前没有正在处理的消息。'); return; }
      const now = Date.now();
      if (action === 'complete') {
        const script = steps(run);
        while (run.cursor < script.length) { const [, type, payload] = script[run.cursor++]; append(run, type, payload, now); }
        finish(current(), run, 'completed', now);
      } else if (action === 'fail') finish(current(), run, 'failed', now);
      refresh();
    }));
    setSidebar(collapsed);
    if (!restore()) seedDemo(); else refresh(true);
    window.setInterval(tick, 250);
