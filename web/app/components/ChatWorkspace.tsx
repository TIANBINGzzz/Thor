"use client";

import { useRef, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MODELS, type ModelOption } from "../lib/models";
import { type AgentEvent, readAgentStream } from "../lib/agent-stream";
import { CheckIcon, ChevronIcon, CopyIcon, MultimodalIcon, PlusIcon, RefreshIcon, SendIcon, SparkIcon, StatsIcon, StopIcon, TextModelIcon } from "./icons";

type Session = { id: string; title: string; modelId: string; createdAt: number; updatedAt: number };
type Message = { id: string; role: "user" | "assistant"; content: string; events?: AgentEvent[]; tokens?: number | null; cost?: number | null; createdAt?: number };
type SessionFile = { id: string; sessionId: string; name: string; contentType: string; size: number; createdAt: number; source?: string; url: string };
type Preview = { file: SessionFile; url: string; text?: string };
type ReferenceSource = { type: string; label: string; hint: string };
type ReferenceItem = { value: string; label: string; reference: string };
type ReferenceTrigger = { anchor: number; end: number; source: string; query: string };

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function sessionTime(value: number) {
  const date = new Date(value);
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function getClientId() {
  const key = "luma-client-id";
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID().replaceAll("-", "");
    localStorage.setItem(key, value);
  }
  return value;
}

function mergeRuntimeEvent(events: AgentEvent[], event: AgentEvent) {
  const current = [...events];
  const last = current.at(-1);
  if (event.type === "thinking" && last?.type === "thinking" && last.scope === event.scope) {
    current[current.length - 1] = { ...last, text: `${last.text || ""}${event.text || ""}` };
    return current;
  }
  if (event.type === "tool_progress" && event.id) {
    const index = current.findLastIndex((item) => item.type === "tool_progress" && item.id === event.id);
    if (index !== -1) {
      current[index] = event;
      return current;
    }
  }
  return [...current, event].slice(-120);
}

function RuntimeEvents({ events = [] }: { events?: AgentEvent[] }) {
  const visible = events.filter((event) => ["init", "thinking", "subagent", "tool_use", "tool_progress", "tool_result", "activity", "error"].includes(event.type));
  if (!visible.length) return null;
  return <div className="runtime-events">{visible.map((event, index) => {
    if (event.type === "thinking") return <details key={`${event.type}-${index}`} className="runtime-detail"><summary>思考过程</summary><pre>{event.text}</pre></details>;
    if (event.type === "tool_use") return <details key={`${event.type}-${event.id || index}`} className="runtime-detail"><summary>{event.name || "工具调用"}</summary>{event.input && <pre>{event.input}</pre>}</details>;
    if (event.type === "tool_progress") return <div key={`${event.type}-${event.id || index}`} className="runtime-line">{event.seconds ? `${event.seconds}s` : "运行中"}</div>;
    if (event.type === "tool_result") return <div key={`${event.type}-${event.id || index}`} className={event.isError ? "runtime-line runtime-error" : "runtime-line"}>{event.isError ? "工具执行失败" : "工具执行完成"}</div>;
    if (event.type === "subagent") return <div key={`${event.type}-${index}`} className="runtime-line">{event.subagentType || "子代理"}{event.description ? ` · ${event.description}` : ""}</div>;
    if (event.type === "init") return <div key={`${event.type}-${index}`} className="runtime-line">{event.tools || 0} 工具 · {event.skills?.length || 0} Skills · {event.agents?.length || 0} 子代理</div>;
    if (event.type === "error") return <div key={`${event.type}-${index}`} className="runtime-line runtime-error">{event.message}</div>;
    return <div key={`${event.type}-${index}`} className="runtime-line">{event.label}{event.detail ? ` · ${event.detail}` : ""}</div>;
  })}</div>;
}

function AssistantContent({ message }: { message: Message }) {
  return <>
    {message.content && <div className="message-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>}
    <RuntimeEvents events={message.events} />
  </>;
}

function detectReference(value: string, caret: number, sources: ReferenceSource[], fallbackSource: string): ReferenceTrigger | null {
  const before = value.slice(0, caret);
  const anchor = before.lastIndexOf("@");
  if (anchor === -1 || (anchor > 0 && !/\s/.test(before[anchor - 1]))) return null;
  const typed = before.slice(anchor + 1);
  if (/\s/.test(typed)) return null;
  const scoped = typed.match(/^([a-z][a-z0-9_]*):(.*)$/);
  if (scoped && sources.some((source) => source.type === scoped[1])) {
    let query = scoped[2];
    try { query = decodeURIComponent(query); } catch { /* keep partially typed escapes */ }
    return { anchor, end: caret, source: scoped[1], query };
  }
  return fallbackSource ? { anchor, end: caret, source: fallbackSource, query: typed } : null;
}

export function ChatWorkspace({ initialSessionId = null }: { initialSessionId?: string | null }) {
  const router = useRouter();
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [files, setFiles] = useState<SessionFile[]>([]);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>(MODELS);
  const [selectedModel, setSelectedModel] = useState(MODELS[0]);
  const [modelOpen, setModelOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(Boolean(initialSessionId));
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pointer, setPointer] = useState({ x: 50, y: 0 });
  const [referenceSources, setReferenceSources] = useState<ReferenceSource[]>([]);
  const [referenceTrigger, setReferenceTrigger] = useState<ReferenceTrigger | null>(null);
  const [referenceItems, setReferenceItems] = useState<ReferenceItem[]>([]);
  const [referenceIndex, setReferenceIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const streamController = useRef<AbortController | null>(null);
  const referenceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const messageSequence = useRef(0);
  const clientId = useRef("");
  const sessionAvailable = !sessionId || sessions.some((session) => session.id === sessionId);

  async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("x-luma-client-id", clientId.current);
    if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
    const response = await fetch(path, { ...init, headers });
    const data = await response.json().catch(() => ({})) as T & { error?: string };
    if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
    return data;
  }

  async function refreshSessions() {
    const data = await api<{ sessions: Session[] }>("/api/sessions");
    setSessions(data.sessions);
  }

  async function loadSession(id: string, showLoading = true) {
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const data = await api<{ session: Session; messages: Message[]; files: SessionFile[] }>(`/api/sessions/${id}`);
      setSessionId(id);
      setMessages(data.messages);
      setFiles(data.files);
      setSelectedModel(modelOptions.find((model) => model.id === data.session.modelId) || { id: data.session.modelId, modality: "text" });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法载入会话");
      setMessages([]);
      setFiles([]);
    } finally {
      if (showLoading) setLoading(false);
    }
  }

  useEffect(() => {
    clientId.current = getClientId();
    queueMicrotask(async () => {
      try {
        const [sessionData, modelData, sourceData] = await Promise.all([
          api<{ sessions: Session[] }>("/api/sessions"),
          api<{ models: string[] }>("/api/models"),
          api<{ sources: ReferenceSource[] }>("/api/sources"),
        ]);
        setSessions(sessionData.sessions);
        const options = modelData.models.map((id) => MODELS.find((model) => model.id === id) || { id, modality: "text" as const });
        if (options.length) {
          setModelOptions(options);
          setSelectedModel(options[0]);
        }
        setReferenceSources(sourceData.sources);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "无法初始化工作区");
      }
    });
    return () => {
      streamController.current?.abort();
      if (referenceTimer.current) clearTimeout(referenceTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!clientId.current) return;
    queueMicrotask(() => {
      if (initialSessionId) loadSession(initialSessionId);
      else {
        setSessionId(null);
        setMessages([]);
        setFiles([]);
        setLoading(false);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId]);

  async function createSession() {
    const data = await api<{ session: Session }>("/api/sessions", { method: "POST", body: JSON.stringify({ modelId: selectedModel.id }) });
    setSessionId(data.session.id);
    setSessions((current) => [data.session, ...current]);
    window.history.replaceState(null, "", `/chat/${data.session.id}`);
    return data.session.id;
  }

  async function resetChat() {
    stopStreaming();
    setSessionId(null);
    setMessages([]);
    setFiles([]);
    setInput("");
    setError(null);
    router.push("/");
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function stopStreaming() {
    streamController.current?.abort();
    streamController.current = null;
    setStreaming(false);
  }

  async function selectModel(model: ModelOption) {
    setSelectedModel(model);
    setModelOpen(false);
    if (sessionId) {
      await api(`/api/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify({ modelId: model.id }) });
      setSessions((current) => current.map((session) => session.id === sessionId ? { ...session, modelId: model.id, updatedAt: Date.now() } : session));
    }
  }

  function updateAssistant(id: string, update: (message: Message) => Message) {
    setMessages((current) => current.map((message) => message.id === id ? update(message) : message));
  }

  async function submit(promptOverride?: string) {
    const prompt = (promptOverride ?? input).trim();
    if (!prompt || streaming) return;
    setError(null);
    try {
      if (!sessionAvailable) throw new Error("当前链接的会话不存在，请从侧边栏新建或打开已有会话");
      const activeId = sessionId || await createSession();
      messageSequence.current += 1;
      const tempId = `stream-${activeId}-${messageSequence.current}`;
      const userId = `user-${activeId}-${messageSequence.current}`;
      setMessages((current) => [...current, { id: userId, role: "user", content: prompt }, { id: tempId, role: "assistant", content: "", events: [] }]);
      setInput("");
      setReferenceTrigger(null);
      setReferenceItems([]);
      setStreaming(true);
      const controller = new AbortController();
      streamController.current = controller;
      const response = await fetch(`/api/sessions/${activeId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-luma-client-id": clientId.current },
        body: JSON.stringify({ prompt, modelId: selectedModel.id }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({})) as { error?: string };
        throw new Error(detail.error || `请求失败 (${response.status})`);
      }
      await readAgentStream(response, (event) => {
        if (event.type === "text" && (!event.scope || event.scope === "main")) {
          updateAssistant(tempId, (message) => ({ ...message, content: `${message.content}${event.text || ""}` }));
        } else if (event.type === "result") {
          updateAssistant(tempId, (message) => ({
            ...message,
            tokens: Number(event.inputTokens || 0) + Number(event.outputTokens || 0),
            cost: event.costUsd ?? null,
          }));
        } else if (event.type === "error") {
          setError(event.message || "生成失败");
          updateAssistant(tempId, (message) => ({ ...message, events: mergeRuntimeEvent(message.events || [], event) }));
        } else if (event.type !== "done") {
          updateAssistant(tempId, (message) => ({ ...message, events: mergeRuntimeEvent(message.events || [], event) }));
        }
      });
      await Promise.all([loadSession(activeId, false), refreshSessions()]);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) {
        setError(caught instanceof Error ? caught.message : "发送失败");
      }
    } finally {
      streamController.current = null;
      setStreaming(false);
    }
  }

  async function retryLast() {
    const previous = [...messages].reverse().find((message) => message.role === "user");
    if (previous) await submit(previous.content);
  }

  async function uploadFile(upload: File) {
    if (upload.size > 10 * 1024 * 1024) { setError("单个文件不能超过 10 MB"); return; }
    setUploading(true);
    setError(null);
    try {
      const activeId = sessionId || await createSession();
      const form = new FormData();
      form.append("file", upload);
      const data = await api<{ file: SessionFile }>(`/api/sessions/${activeId}/files`, { method: "POST", body: form });
      setFiles((current) => [...current, data.file]);
      await refreshSessions();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "上传失败"); }
    finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = ""; }
  }

  async function openPreview(file: SessionFile) {
    setError(null);
    try {
      const response = await fetch(file.url, { headers: { "x-luma-client-id": clientId.current } });
      if (!response.ok) throw new Error("文件预览加载失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const text = file.contentType.startsWith("text/") || /\.(md|json|csv|log)$/i.test(file.name) ? await blob.text() : undefined;
      if (preview?.url) URL.revokeObjectURL(preview.url);
      setPreview({ file, url, text });
    } catch (caught) { setError(caught instanceof Error ? caught.message : "文件预览失败"); }
  }

  function closePreview() {
    if (preview?.url) URL.revokeObjectURL(preview.url);
    setPreview(null);
  }

  async function copyLast() {
    const last = [...messages].reverse().find((message) => message.role === "assistant");
    if (!last) return;
    await navigator.clipboard.writeText(last.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  function refreshReferences(trigger: ReferenceTrigger) {
    if (referenceTimer.current) clearTimeout(referenceTimer.current);
    referenceTimer.current = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ source: trigger.source, q: trigger.query, limit: "20", offset: "0" });
        const page = await api<{ items: ReferenceItem[] }>(`/api/options?${params}`);
        setReferenceItems(page.items);
        setReferenceIndex(0);
      } catch {
        setReferenceItems([]);
      }
    }, 120);
  }

  function syncReferences(value: string, caret: number) {
    const trigger = detectReference(value, caret, referenceSources, referenceTrigger?.source || referenceSources[0]?.type || "");
    setReferenceTrigger(trigger);
    if (trigger) refreshReferences(trigger);
    else setReferenceItems([]);
  }

  function switchReferenceSource(source: string) {
    if (!referenceTrigger) return;
    const next = { ...referenceTrigger, source };
    setReferenceTrigger(next);
    refreshReferences(next);
    textareaRef.current?.focus();
  }

  function insertReference(item: ReferenceItem) {
    if (!referenceTrigger) return;
    const before = input.slice(0, referenceTrigger.anchor);
    const after = input.slice(referenceTrigger.end);
    const next = `${before}${item.reference} ${after}`;
    const position = before.length + item.reference.length + 1;
    setInput(next);
    setReferenceTrigger(null);
    setReferenceItems([]);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(position, position);
    });
  }

  function handleInputKey(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (referenceTrigger && referenceItems.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setReferenceIndex((current) => (current + (event.key === "ArrowDown" ? 1 : -1) + referenceItems.length) % referenceItems.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        insertReference(referenceItems[referenceIndex]);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setReferenceTrigger(null);
        setReferenceItems([]);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <main className="app-shell" data-history-open={historyOpen}>
      <aside className="rail" aria-label="历史会话">
        <div className="rail-head">
          <button className="brand-mark" onClick={() => setHistoryOpen((value) => !value)} aria-label="展开历史会话"><span /></button>
          <button className="rail-button" onClick={resetChat} aria-label="新建对话"><PlusIcon /></button>
        </div>
        <div className="history-list">
          <div className="history-label">历史会话</div>
          {sessions.length === 0 ? <p className="history-empty">还没有保存的对话</p> : sessions.map((session) => (
            <button key={session.id} className="history-item" data-active={session.id === sessionId} onClick={() => { setHistoryOpen(false); router.push(`/chat/${session.id}`); }}>
              <span>{session.title}</span><time>{sessionTime(session.updatedAt)}</time>
            </button>
          ))}
        </div>
        <div className="rail-spacer" />
        <button className="rail-stats" onClick={() => router.push("/stats")} aria-label="用量统计"><StatsIcon /><span>用量统计</span></button>
        <div className="rail-foot"><span className="connection-dot" /><small>Agent 已连接</small></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="history-toggle" onClick={() => setHistoryOpen((value) => !value)} aria-label="打开历史会话"><span /><span /><span /></button>
          {sessionId && <div className="session-route" title={sessionId}>{`session / ${sessionId.slice(0, 8)}`}</div>}
        </header>

        <div className="conversation" aria-live="polite">
          {loading ? <div className="session-loading"><i /><i /><i /></div> : messages.length === 0 && files.length === 0 ? null : <>
            {files.length > 0 && <section className="session-files" aria-label="会话文件"><div className="file-section-head"><span>会话文件</span><b>{files.length}</b></div><div className="file-grid">{files.map((file) => <button key={file.id} className="file-card" onClick={() => openPreview(file)}><span className="file-type">{file.name.split(".").pop()?.slice(0, 4).toUpperCase() || "FILE"}</span><span className="file-info"><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></span><span className="file-open">预览</span></button>)}</div></section>}
            {messages.map((message, index) => <article key={message.id} className={`message message-${message.role}`} style={{ animationDelay: `${Math.min(index, 4) * 45}ms` }}><div className="message-label">{message.role === "user" ? "你" : selectedModel.id}</div><div className="message-content">{message.role === "assistant" ? <AssistantContent message={message} /> : message.content}{message.role === "assistant" && !message.content && !(message.events?.length) && <span className="thinking"><i /><i /><i /></span>}{message.role === "assistant" && streaming && index === messages.length - 1 && message.content && <span className="stream-caret" />}</div>{message.role === "assistant" && (message.tokens != null || message.cost != null) && <div className="message-meta">{message.tokens != null && <span>{message.tokens} tokens</span>}{message.cost != null && <span>实际费用 ${message.cost.toFixed(4)}</span>}<span>已保存</span></div>}</article>)}
            {messages.some((message) => message.role === "assistant" && message.content) && <div className="message-actions"><button onClick={copyLast}>{copied ? <CheckIcon /> : <CopyIcon />}{copied ? "已复制" : "复制"}</button><button onClick={retryLast}><RefreshIcon />重试</button></div>}
          </>}
        </div>

        <div className="composer-zone">
          {error && <div className="inline-error" role="alert">{error}<button onClick={() => setError(null)}>关闭</button></div>}
          <div className="composer" style={{ "--pointer-x": `${pointer.x}%`, "--pointer-y": `${pointer.y}%` } as React.CSSProperties} onPointerMove={(event) => { const rect = event.currentTarget.getBoundingClientRect(); setPointer({ x: ((event.clientX - rect.left) / rect.width) * 100, y: ((event.clientY - rect.top) / rect.height) * 100 }); }}>
            {referenceTrigger && <div className="reference-menu" role="listbox"><div className="reference-sources">{referenceSources.map((source) => <button key={source.type} data-active={source.type === referenceTrigger.source} onMouseDown={(event) => { event.preventDefault(); switchReferenceSource(source.type); }}>{source.label}</button>)}</div><div className="reference-options">{referenceItems.length ? referenceItems.map((item, index) => <button key={item.reference} data-active={index === referenceIndex} onMouseDown={(event) => { event.preventDefault(); insertReference(item); }}><strong>{item.label}</strong><span>{item.reference}</span></button>) : <p>没有匹配项</p>}</div></div>}
            <textarea ref={textareaRef} value={input} onChange={(event) => { setInput(event.target.value); syncReferences(event.target.value, event.target.selectionStart); }} onClick={(event) => syncReferences(event.currentTarget.value, event.currentTarget.selectionStart)} onKeyDown={handleInputKey} placeholder={sessionAvailable ? "输入消息…" : "此会话不可用"} rows={1} aria-label="消息" disabled={!sessionAvailable} />
            <div className="composer-footer"><div className="composer-tools">
              <button className="composer-model-trigger" onClick={() => setModelOpen((value) => !value)} aria-expanded={modelOpen} aria-label={`选择模型，当前 ${selectedModel.id}`}><SparkIcon /><span>{selectedModel.id}</span><ChevronIcon className={modelOpen ? "chevron-up" : ""} /></button>
              {modelOpen && <div className="model-menu composer-model-menu" role="menu">{modelOptions.map((model) => <button key={model.id} className="model-option" data-active={selectedModel.id === model.id} onClick={() => selectModel(model)} role="menuitem" aria-label={`${model.id}，${model.modality === "multimodal" ? "多模态" : "纯文本"}`}><span className="model-modality" title={model.modality === "multimodal" ? "多模态" : "纯文本"}>{model.modality === "multimodal" ? <MultimodalIcon /> : <TextModelIcon />}</span><strong>{model.id}</strong>{selectedModel.id === model.id && <CheckIcon />}</button>)}</div>}
              <input ref={fileInputRef} type="file" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadFile(file); }} /><button className="attach-button" onClick={() => fileInputRef.current?.click()} disabled={uploading} aria-label="上传文件"><PlusIcon /><span>{uploading ? "上传中" : "添加文件"}</span></button>
            </div><button className="send-button" data-streaming={streaming} onClick={streaming ? stopStreaming : () => submit()} disabled={!streaming && (!input.trim() || !sessionAvailable)} aria-label={streaming ? "停止生成" : "发送消息"}>{streaming ? <StopIcon /> : <SendIcon />}</button></div>
          </div>
          <p className="disclaimer">文件最大 10 MB · 输入 @ 引用文件或依赖。</p>
        </div>
      </section>

      {historyOpen && <button className="history-backdrop" onClick={() => setHistoryOpen(false)} aria-label="关闭历史会话" />}
      {preview && <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label={`预览 ${preview.file.name}`}><div className="preview-panel"><header><div><strong>{preview.file.name}</strong><span>{formatBytes(preview.file.size)} · {preview.file.contentType}</span></div><div><a href={preview.url} download={preview.file.name}>下载</a><button onClick={closePreview}>关闭</button></div></header><div className="preview-content">{preview.file.contentType.startsWith("image/") ? <object data={preview.url} type={preview.file.contentType} aria-label={preview.file.name} /> : preview.file.contentType === "application/pdf" ? <iframe src={preview.url} title={preview.file.name} /> : preview.text !== undefined ? <pre>{preview.text}</pre> : <div className="generic-preview"><span>{preview.file.name.split(".").pop()?.toUpperCase() || "FILE"}</span><p>此文件无法在浏览器中直接预览。</p><a href={preview.url} download={preview.file.name}>下载文件</a></div>}</div></div></div>}
    </main>
  );
}
