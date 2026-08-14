"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { MODELS, type ModelOption } from "../lib/models";
import { CheckIcon, ChevronIcon, CopyIcon, MultimodalIcon, PlusIcon, RefreshIcon, SendIcon, SparkIcon, StatsIcon, StopIcon, TextModelIcon } from "./icons";

type Session = { id: string; title: string; modelId: string; createdAt: number; updatedAt: number };
type Message = { id: string; role: "user" | "assistant"; content: string; tokens?: number | null; cost?: number | null; createdAt?: number };
type SessionFile = { id: string; sessionId: string; name: string; contentType: string; size: number; createdAt: number; url: string };
type Preview = { file: SessionFile; url: string; text?: string };

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

export function ChatWorkspace({ initialSessionId = null }: { initialSessionId?: string | null }) {
  const router = useRouter();
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [files, setFiles] = useState<SessionFile[]>([]);
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const streamTimer = useRef<ReturnType<typeof setInterval> | null>(null);
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

  async function loadSession(id: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await api<{ session: Session; messages: Message[]; files: SessionFile[] }>(`/api/sessions/${id}`);
      setSessionId(id);
      setMessages(data.messages);
      setFiles(data.files);
      setSelectedModel(MODELS.find((model) => model.id === data.session.modelId) || MODELS[0]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法载入会话");
      setMessages([]);
      setFiles([]);
    } finally { setLoading(false); }
  }

  useEffect(() => {
    clientId.current = getClientId();
    queueMicrotask(() => refreshSessions().catch(() => setError("无法读取历史会话")));
    return () => {
      if (streamTimer.current) clearInterval(streamTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    // Route changes are the source of truth for the active conversation.
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
    if (streamTimer.current) clearInterval(streamTimer.current);
    streamTimer.current = null;
    setStreaming(false);
  }

  async function selectModel(model: ModelOption) {
    setSelectedModel(model);
    setModelOpen(false);
    if (sessionId) {
      await api(`/api/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify({ modelId: model.id }) });
      setSessions((current) => current.map((session) => session.id === sessionId ? { ...session, modelId: model.id } : session));
    }
  }

  async function submit() {
    const prompt = input.trim();
    if (!prompt || streaming) return;
    setError(null);
    try {
      if (!sessionAvailable) throw new Error("当前链接的会话不存在，请从侧边栏新建或打开已有会话");
      const activeId = sessionId || await createSession();
      const saved = await api<{ message: Message }>(`/api/sessions/${activeId}/messages`, { method: "POST", body: JSON.stringify({ role: "user", content: prompt }) });
      const tempId = `stream-${Date.now()}`;
      setMessages((current) => [...current, saved.message, { id: tempId, role: "assistant", content: "" }]);
      setInput("");
      setStreaming(true);

      if (messages.length === 0) {
        const title = prompt.slice(0, 26);
        await api(`/api/sessions/${activeId}`, { method: "PATCH", body: JSON.stringify({ title }) });
        setSessions((current) => current.map((session) => session.id === activeId ? { ...session, title, updatedAt: Date.now() } : session));
      }

      const reply = files.length
        ? `已收到你的问题和当前会话中的 ${files.length} 个文件。文件与消息均按 session_id 隔离保存；接入 Agent SDK 后，这里将流式返回真实分析结果。`
        : "这是一个持久化会话。消息会按 session_id 隔离保存；接入 Agent SDK 后，这里将流式返回真实模型结果。";
      let cursor = 0;
      streamTimer.current = setInterval(() => {
        cursor += 2;
        const complete = cursor >= reply.length;
        setMessages((current) => current.map((message) => message.id === tempId ? { ...message, content: reply.slice(0, cursor) } : message));
        if (complete) {
          stopStreaming();
          api<{ message: Message }>(`/api/sessions/${activeId}/messages`, { method: "POST", body: JSON.stringify({ role: "assistant", content: reply }) })
            .then(({ message }) => setMessages((current) => current.map((item) => item.id === tempId ? message : item)))
            .then(refreshSessions)
            .catch(() => setError("回复已显示，但保存失败"));
        }
      }, 24);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "发送失败"); }
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
        <div className="rail-foot"><span className="connection-dot" /><small>数据已隔离</small></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="history-toggle" onClick={() => setHistoryOpen((value) => !value)} aria-label="打开历史会话"><span /><span /><span /></button>
          {sessionId && <div className="session-route" title={sessionId}>{`session / ${sessionId.slice(0, 8)}`}</div>}
        </header>

        <div className="conversation" aria-live="polite">
          {loading ? <div className="session-loading"><i /><i /><i /></div> : messages.length === 0 && files.length === 0 ? null : <>
            {files.length > 0 && <section className="session-files" aria-label="会话文件"><div className="file-section-head"><span>会话文件</span><b>{files.length}</b></div><div className="file-grid">{files.map((file) => <button key={file.id} className="file-card" onClick={() => openPreview(file)}><span className="file-type">{file.name.split(".").pop()?.slice(0, 4).toUpperCase() || "FILE"}</span><span className="file-info"><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></span><span className="file-open">预览</span></button>)}</div></section>}
            {messages.map((message, index) => <article key={message.id} className={`message message-${message.role}`} style={{ animationDelay: `${Math.min(index, 4) * 45}ms` }}><div className="message-label">{message.role === "user" ? "你" : selectedModel.id}</div><div className="message-content">{message.content || <span className="thinking"><i /><i /><i /></span>}{message.role === "assistant" && streaming && index === messages.length - 1 && message.content && <span className="stream-caret" />}</div>{message.role === "assistant" && (message.tokens != null || message.cost != null) && <div className="message-meta">{message.tokens != null && <span>{message.tokens} tokens</span>}{message.cost != null && <span>实际费用 ¥{message.cost.toFixed(4)}</span>}<span>已保存</span></div>}</article>)}
            {messages.some((message) => message.role === "assistant" && message.content) && <div className="message-actions"><button onClick={copyLast}>{copied ? <CheckIcon /> : <CopyIcon />}{copied ? "已复制" : "复制"}</button><button><RefreshIcon />重试</button></div>}
          </>}
        </div>

        <div className="composer-zone">
          {error && <div className="inline-error" role="alert">{error}<button onClick={() => setError(null)}>关闭</button></div>}
          <div className="composer" style={{ "--pointer-x": `${pointer.x}%`, "--pointer-y": `${pointer.y}%` } as React.CSSProperties} onPointerMove={(event) => { const rect = event.currentTarget.getBoundingClientRect(); setPointer({ x: ((event.clientX - rect.left) / rect.width) * 100, y: ((event.clientY - rect.top) / rect.height) * 100 }); }}>
            <textarea ref={textareaRef} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} placeholder={sessionAvailable ? "输入消息…" : "此会话不可用"} rows={1} aria-label="消息" disabled={!sessionAvailable} />
            <div className="composer-footer"><div className="composer-tools">
              <button className="composer-model-trigger" onClick={() => setModelOpen((value) => !value)} aria-expanded={modelOpen} aria-label={`选择模型，当前 ${selectedModel.id}`}><SparkIcon /><span>{selectedModel.id}</span><ChevronIcon className={modelOpen ? "chevron-up" : ""} /></button>
              {modelOpen && <div className="model-menu composer-model-menu" role="menu">{MODELS.map((model) => <button key={model.id} className="model-option" data-active={selectedModel.id === model.id} onClick={() => selectModel(model)} role="menuitem" aria-label={`${model.id}，${model.modality === "multimodal" ? "多模态" : "纯文本"}`}><span className="model-modality" title={model.modality === "multimodal" ? "多模态" : "纯文本"}>{model.modality === "multimodal" ? <MultimodalIcon /> : <TextModelIcon />}</span><strong>{model.id}</strong>{selectedModel.id === model.id && <CheckIcon />}</button>)}</div>}
              <input ref={fileInputRef} type="file" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadFile(file); }} /><button className="attach-button" onClick={() => fileInputRef.current?.click()} disabled={uploading} aria-label="上传文件"><PlusIcon /><span>{uploading ? "上传中" : "添加文件"}</span></button>
            </div><button className="send-button" data-streaming={streaming} onClick={streaming ? stopStreaming : submit} disabled={!streaming && (!input.trim() || !sessionAvailable)} aria-label={streaming ? "停止生成" : "发送消息"}>{streaming ? <StopIcon /> : <SendIcon />}</button></div>
          </div>
          <p className="disclaimer">文件最大 10 MB · 会话与文件按 session_id 隔离。</p>
        </div>
      </section>

      {historyOpen && <button className="history-backdrop" onClick={() => setHistoryOpen(false)} aria-label="关闭历史会话" />}
      {preview && <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label={`预览 ${preview.file.name}`}><div className="preview-panel"><header><div><strong>{preview.file.name}</strong><span>{formatBytes(preview.file.size)} · {preview.file.contentType}</span></div><div><a href={preview.url} download={preview.file.name}>下载</a><button onClick={closePreview}>关闭</button></div></header><div className="preview-content">{preview.file.contentType.startsWith("image/") ? <object data={preview.url} type={preview.file.contentType} aria-label={preview.file.name} /> : preview.file.contentType === "application/pdf" ? <iframe src={preview.url} title={preview.file.name} /> : preview.text !== undefined ? <pre>{preview.text}</pre> : <div className="generic-preview"><span>{preview.file.name.split(".").pop()?.toUpperCase() || "FILE"}</span><p>此文件无法在浏览器中直接预览。</p><a href={preview.url} download={preview.file.name}>下载文件</a></div>}</div></div></div>}
    </main>
  );
}
