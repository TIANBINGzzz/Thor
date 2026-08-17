"use client";

import { useRef, useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  useLocalRuntime,
  AssistantRuntimeProvider,
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  type ReasoningMessagePartProps,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import { MODELS, type ModelOption } from "../lib/models";
import {
  createChatModelAdapter,
  isRuntimeEventResult,
  isRuntimeToolName,
  persistedMessagesToThreadMessages,
  type PersistedMessage,
} from "../lib/assistant-ui-adapter";
import { CheckIcon, ChevronIcon, DownloadIcon, MenuIcon, MoreHorizontalIcon, MultimodalIcon, PencilIcon, PlusIcon, SendIcon, SparkIcon, StatsIcon, TextModelIcon, TrashIcon } from "./icons";
import { BRAND } from "../lib/brand";
import { ThemeToggle } from "./ThemeToggle";
import { ConfirmDialog } from "./ConfirmDialog";
import { Portal } from "./Portal";
import { SkillCreator } from "./SkillCreator";
import { parseReferences } from "./ReferenceChips";

type Session = { id: string; title: string; modelId: string; createdAt: number; updatedAt: number };
type SessionFile = { id: string; sessionId: string; name: string; contentType: string; size: number; createdAt: number; source?: string; url: string };
type Preview = { file: SessionFile; text?: string };
type ReferenceSource = { type: string; label: string; hint: string };
type ReferenceItem = { value: string; label: string; reference: string };
type ReferenceTrigger = { anchor: number; end: number; source: string; query: string };

function getClientId() {
  const key = "luma-client-id";
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID().replaceAll("-", "");
    localStorage.setItem(key, value);
  }
  return value;
}

function sessionTime(value: number) {
  const date = new Date(value);
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
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

function ReasoningPart({ text, status }: ReasoningMessagePartProps) {
  if (!text) return null;
  return (
    <details className="runtime-detail reasoning-detail" open={status.type === "running"}>
      <summary>
        <span>思考过程</span>
        <small>{status.type === "running" ? "进行中" : "已完成"}</small>
      </summary>
      <pre>{text}</pre>
    </details>
  );
}

function ToolPart({ toolName, argsText, result, isError, status }: ToolCallMessagePartProps) {
  if (isRuntimeToolName(toolName) && isRuntimeEventResult(result)) {
    return (
      <div className={result.isError ? "runtime-line runtime-error" : "runtime-line"}>
        <span>{result.label}</span>
        {result.detail && <small>{result.detail}</small>}
      </div>
    );
  }

  const completed = result !== undefined;
  const resultText = typeof result === "string" ? result : result === undefined ? "" : JSON.stringify(result, null, 2);
  return (
    <details className={isError ? "runtime-detail tool-detail runtime-error" : "runtime-detail tool-detail"}>
      <summary>
        <span>{toolName || "工具调用"}</span>
        <small>{completed ? (isError ? "失败" : "完成") : status.type === "running" ? "运行中" : "等待结果"}</small>
      </summary>
      {argsText && <pre>{argsText}</pre>}
      {resultText && <pre className="tool-result">{resultText}</pre>}
    </details>
  );
}

function CustomMessage() {
  return (
    <MessagePrimitive.Root>
      <div className="message-content">
        <MessagePrimitive.Content
          components={{
            Text: ({ text }: { text: string }) => (
              <div className="message-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
              </div>
            ),
            Reasoning: ReasoningPart,
            tools: { Fallback: ToolPart },
          }}
        />
      </div>
    </MessagePrimitive.Root>
  );
}

// Custom composer with reference picker
function CustomComposer({
  referenceSources,
  clientId,
  onFileUpload,
  uploading,
  modelOptions,
  selectedModel,
  onModelSelect,
}: {
  referenceSources: ReferenceSource[];
  clientId: string;
  onFileUpload: (file: File) => void;
  uploading: boolean;
  modelOptions: ModelOption[];
  selectedModel: ModelOption;
  onModelSelect: (model: ModelOption) => void;
}) {
  const [inputValue, setInputValue] = useState("");
  const [referenceTrigger, setReferenceTrigger] = useState<ReferenceTrigger | null>(null);
  const [referenceItems, setReferenceItems] = useState<ReferenceItem[]>([]);
  const [referenceIndex, setReferenceIndex] = useState(0);
  const [modelOpen, setModelOpen] = useState(false);
  const [modelIndex, setModelIndex] = useState(0);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [showSkillCreator, setShowSkillCreator] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const referenceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const referenceMenuRef = useRef<HTMLDivElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const modelTriggerRef = useRef<HTMLButtonElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refreshReferences = useCallback(
    (trigger: ReferenceTrigger) => {
      if (referenceTimer.current) clearTimeout(referenceTimer.current);
      referenceTimer.current = setTimeout(async () => {
        try {
          const params = new URLSearchParams({ source: trigger.source, q: trigger.query, limit: "20", offset: "0" });
          const page = await fetch(`/api/options?${params}`, {
            headers: { "x-luma-client-id": clientId },
          }).then((r) => r.json()) as { items: ReferenceItem[] };
          setReferenceItems(page.items);
          setReferenceIndex(0);
        } catch {
          setReferenceItems([]);
        }
      }, 120);
    },
    [clientId]
  );

  // 监听消息发送，清空输入框
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // 监听表单提交事件
    const form = textarea.closest('form');
    if (!form) return;

    const handleSubmit = () => {
      // 延迟清空，确保消息已发送
      setTimeout(() => {
        setInputValue('');
        setReferenceTrigger(null);
        setReferenceItems([]);
      }, 50);
    };

    form.addEventListener('submit', handleSubmit);
    return () => form.removeEventListener('submit', handleSubmit);
  }, []);

  // 监听粘贴事件上传文件
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const handlePaste = async (event: ClipboardEvent) => {
      const items = event.clipboardData?.items;
      if (!items) return;

      for (const item of Array.from(items)) {
        if (item.type.startsWith("image/") || item.type.startsWith("application/")) {
          event.preventDefault();
          const file = item.getAsFile();
          if (file) {
            setPendingFiles((current) => [...current, file]);
          }
          break;
        }
      }
    };

    textarea.addEventListener("paste", handlePaste);
    return () => textarea.removeEventListener("paste", handlePaste);
  }, []);

  // 发送消息前上传待处理文件
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const form = textarea.closest('form');
    if (!form) return;

    const handleSubmit = async () => {
      if (pendingFiles.length > 0) {
        // 上传所有待处理文件
        for (const file of pendingFiles) {
          await onFileUpload(file);
        }
        setPendingFiles([]);
      }
    };

    form.addEventListener('submit', handleSubmit);
    return () => form.removeEventListener('submit', handleSubmit);
  }, [pendingFiles, onFileUpload]);

  const syncReferences = useCallback(
    (value: string, caret: number) => {
      const trigger = detectReference(value, caret, referenceSources, referenceTrigger?.source || referenceSources[0]?.type || "");
      setReferenceTrigger(trigger);
      if (trigger) refreshReferences(trigger);
      else setReferenceItems([]);
    },
    [referenceSources, referenceTrigger?.source, refreshReferences]
  );

  const insertReference = useCallback(
    (item: ReferenceItem) => {
      if (!referenceTrigger || !textareaRef.current) return;
      const value = inputValue;
      const before = value.slice(0, referenceTrigger.anchor);
      const after = value.slice(referenceTrigger.end);
      const next = `${before}${item.reference} ${after}`;
      const position = before.length + item.reference.length + 1;

      setInputValue(next);
      setReferenceTrigger(null);
      setReferenceItems([]);

      requestAnimationFrame(() => {
        textareaRef.current?.focus();
        textareaRef.current?.setSelectionRange(position, position);
      });
    },
    [referenceTrigger, inputValue]
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
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
    },
    [referenceTrigger, referenceItems, referenceIndex, insertReference]
  );

  // Click outside to close reference menu
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (referenceMenuRef.current && !referenceMenuRef.current.contains(event.target as Node) &&
          textareaRef.current && !textareaRef.current.contains(event.target as Node)) {
        setReferenceTrigger(null);
        setReferenceItems([]);
      }
    }
    if (referenceTrigger) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [referenceTrigger]);

  // Click outside to close model menu
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (modelMenuRef.current && !modelMenuRef.current.contains(event.target as Node)) {
        const trigger = document.querySelector('.composer-model-trigger');
        if (trigger && !trigger.contains(event.target as Node)) {
          setModelOpen(false);
        }
      }
    }
    if (modelOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [modelOpen]);

  // Click outside to close add menu
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (!document.querySelector('.composer-add-menu-wrapper')?.contains(target)) {
        setAddMenuOpen(false);
      }
    }
    if (addMenuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [addMenuOpen]);

  useEffect(() => {
    if (!modelOpen) return;
    const selectedIndex = Math.max(0, modelOptions.findIndex((model) => model.id === selectedModel.id));
    setModelIndex(selectedIndex);
    requestAnimationFrame(() => {
      const options = modelMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]');
      options?.[selectedIndex]?.focus();
    });
  }, [modelOpen, modelOptions, selectedModel.id]);

  const selectComposerModel = useCallback((model: ModelOption) => {
    onModelSelect(model);
    setModelOpen(false);
    requestAnimationFrame(() => modelTriggerRef.current?.focus());
  }, [onModelSelect]);

  const handleModelMenuKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setModelOpen(false);
      requestAnimationFrame(() => modelTriggerRef.current?.focus());
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    setModelIndex((current) => {
      let next = current;
      if (event.key === "Home") next = 0;
      else if (event.key === "End") next = modelOptions.length - 1;
      else next = (current + (event.key === "ArrowDown" ? 1 : -1) + modelOptions.length) % modelOptions.length;
      requestAnimationFrame(() => {
        const options = modelMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]');
        options?.[next]?.focus();
      });
      return next;
    });
  }, [modelOptions.length]);

  // Clear input after send
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const observer = new MutationObserver(() => {
      if (textarea.value === "" && inputValue !== "") {
        setInputValue("");
      }
    });

    observer.observe(textarea, { attributes: true, attributeFilter: ["value"] });
    return () => observer.disconnect();
  }, [inputValue]);

  return (
    <div className="custom-composer">
      {referenceTrigger && (
        <div ref={referenceMenuRef} className="reference-menu" role="listbox">
          <div className="reference-sources">
            {referenceSources.map((source) => (
              <button
                key={source.type}
                data-active={source.type === referenceTrigger.source}
                onMouseDown={(event) => {
                  event.preventDefault();
                  const next = { ...referenceTrigger, source: source.type };
                  setReferenceTrigger(next);
                  refreshReferences(next);
                  textareaRef.current?.focus();
                }}
              >
                {source.label}
              </button>
            ))}
          </div>
          <div className="reference-options">
            {referenceItems.length ? (
              referenceItems.map((item, index) => (
                <button
                  key={item.reference}
                  data-active={index === referenceIndex}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    insertReference(item);
                  }}
                >
                  <strong>{item.label}</strong>
                  <span>{item.reference}</span>
                </button>
              ))
            ) : (
              <p>没有匹配项</p>
            )}
          </div>
        </div>
      )}
      <ComposerPrimitive.Root>
        {/* 待上传文件预览 */}
        {pendingFiles.length > 0 && (
          <div className="pending-files">
            {pendingFiles.map((file, index) => (
              <div key={`${file.name}-${index}`} className="pending-file">
                <span className="pending-file-icon">📎</span>
                <span className="pending-file-name">{file.name}</span>
                <span className="pending-file-size">({formatBytes(file.size)})</span>
                <button
                  type="button"
                  className="pending-file-remove"
                  onClick={() => setPendingFiles((files) => files.filter((_, i) => i !== index))}
                  aria-label={`移除 ${file.name}`}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        <ComposerPrimitive.Input
          ref={textareaRef}
          placeholder="输入消息…输入 @ 引用 Skill 或依赖"
          rows={1}
          value={inputValue}
          onChange={(event) => {
            setInputValue(event.target.value);
            syncReferences(event.target.value, event.target.selectionStart);
          }}
          onClick={(event) => {
            syncReferences(event.currentTarget.value, event.currentTarget.selectionStart);
          }}
          onKeyDown={(event) => {
            // 处理引用菜单的键盘导航
            if (referenceTrigger && referenceItems.length > 0) {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setReferenceIndex((current) => (current + 1) % referenceItems.length);
                return;
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setReferenceIndex((current) => (current - 1 + referenceItems.length) % referenceItems.length);
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
          }}
        />
        <div className="composer-actions">
          <div className="composer-left-actions">
            <input
              ref={fileInputRef}
              type="file"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  setPendingFiles((current) => [...current, file]);
                  if (fileInputRef.current) fileInputRef.current.value = "";
                }
              }}
            />
            <div className="composer-add-menu-wrapper">
              <button
                type="button"
                className="composer-add-button"
                onClick={() => setAddMenuOpen((prev) => !prev)}
                aria-label="添加内容"
                aria-expanded={addMenuOpen}
              >
                <PlusIcon />
              </button>
              {addMenuOpen && (
                <div className="composer-add-menu">
                  <button
                    type="button"
                    onClick={() => {
                      fileInputRef.current?.click();
                      setAddMenuOpen(false);
                    }}
                  >
                    <DownloadIcon />
                    <span>上传文件</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowSkillCreator(true);
                      setAddMenuOpen(false);
                    }}
                  >
                    <SparkIcon />
                    <span>创建 Skill</span>
                  </button>
                </div>
              )}
            </div>
            <div className="composer-model-selector">
              <button
                ref={modelTriggerRef}
                type="button"
                className="composer-model-trigger"
                onClick={() => setModelOpen((value) => !value)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                    event.preventDefault();
                    setModelOpen(true);
                  }
                }}
                aria-expanded={modelOpen}
                aria-haspopup="menu"
                aria-label={`选择模型，当前 ${selectedModel.id}`}
              >
                <SparkIcon />
                <span>{selectedModel.id}</span>
                <ChevronIcon className={modelOpen ? "chevron-up" : ""} />
              </button>
              {modelOpen && (
                <div
                  ref={modelMenuRef}
                  className="model-menu composer-model-menu"
                  role="menu"
                  aria-label="选择模型"
                  onKeyDown={handleModelMenuKeyDown}
                >
                  <div className="model-menu-heading">
                    <span>选择模型</span>
                    <small>{modelOptions.length} 个可用</small>
                  </div>
                  {modelOptions.map((model, index) => (
                    <button
                      key={model.id}
                      className="model-option"
                      data-active={selectedModel.id === model.id}
                      onClick={() => selectComposerModel(model)}
                      onMouseEnter={() => setModelIndex(index)}
                      role="menuitemradio"
                      aria-checked={selectedModel.id === model.id}
                      tabIndex={index === modelIndex ? 0 : -1}
                    >
                      <span className="model-modality">
                        {model.modality === "multimodal" ? <MultimodalIcon /> : <TextModelIcon />}
                      </span>
                      <span className="model-option-copy">
                        <strong>{model.id}</strong>
                        <small>{model.modality === "multimodal" ? "文本与图像" : "文本推理"}</small>
                      </span>
                      <span className="model-selected-mark" aria-hidden="true">
                        {selectedModel.id === model.id && <CheckIcon />}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          <ComposerPrimitive.Send className="send-button" aria-label="发送消息">
            <SendIcon />
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
      {showSkillCreator && (
        <Portal>
          <SkillCreator
            onClose={() => setShowSkillCreator(false)}
            onSubmit={(name, description, scenarios) => {
              setShowSkillCreator(false);
              // 插入一个提示消息，让用户通过对话创建
              const message = `帮我创建一个 Skill：\n名称: ${name}\n描述: ${description}${scenarios ? `\n场景: ${scenarios}` : ""}`;
              setInputValue(message);
              textareaRef.current?.focus();
            }}
          />
        </Portal>
      )}
    </div>
  );
}

function HistoryList({
  sessions,
  activeSessionId,
  onSelect,
  onRename,
  onDelete,
}: {
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onRename: (session: Session, title: string) => Promise<boolean>;
  onDelete: (session: Session) => Promise<void>;
}) {
  const [historyMenuId, setHistoryMenuId] = useState<string | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  useEffect(() => {
    if (!historyMenuId && !renamingSessionId) return;
    function handleHistoryInteraction(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent && event.key === "Escape") {
        setHistoryMenuId(null);
        setMenuPosition(null);
        setRenamingSessionId(null);
        setRenameValue("");
        return;
      }
      if (event instanceof MouseEvent) {
        const target = event.target as HTMLElement;
        if (!target.closest(".history-item") && !target.closest(".history-menu")) {
          setHistoryMenuId(null);
          setMenuPosition(null);
        }
      }
    }
    document.addEventListener("mousedown", handleHistoryInteraction);
    document.addEventListener("keydown", handleHistoryInteraction);
    return () => {
      document.removeEventListener("mousedown", handleHistoryInteraction);
      document.removeEventListener("keydown", handleHistoryInteraction);
    };
  }, [historyMenuId, renamingSessionId]);

  function openMenu(sessionId: string, event: React.MouseEvent<HTMLButtonElement>) {
    const button = event.currentTarget;
    const rect = button.getBoundingClientRect();
    const menuWidth = 154;
    const menuHeight = 80;

    // 默认在按钮右下方
    let top = rect.bottom + 2;
    let left = rect.right - menuWidth - 4;

    // 如果会超出底部，向上弹
    if (top + menuHeight > window.innerHeight - 20) {
      top = rect.top - menuHeight - 2;
    }

    // 如果会超出右侧，向左调整
    if (left < 10) {
      left = 10;
    }

    setMenuPosition({ top, left });
    setHistoryMenuId(sessionId);
  }

  function beginRename(session: Session) {
    setHistoryMenuId(null);
    setMenuPosition(null);
    setRenamingSessionId(session.id);
    setRenameValue(session.title);
  }

  function cancelRename() {
    setRenamingSessionId(null);
    setRenameValue("");
  }

  async function saveRename(session: Session) {
    const title = renameValue.trim();
    if (!title) return;
    if (title === session.title) {
      cancelRename();
      return;
    }
    if (await onRename(session, title)) cancelRename();
  }

  if (sessions.length === 0) {
    return <p className="history-empty">还没有保存的对话</p>;
  }

  return (
    <>
      {sessions.map((session) => (
        <div
          key={session.id}
          className="history-item"
          data-active={session.id === activeSessionId}
          data-menu-open={historyMenuId === session.id}
        >
          {renamingSessionId === session.id ? (
            <form
              className="history-item-main history-item-rename"
              onSubmit={(event) => {
                event.preventDefault();
                void saveRename(session);
              }}
            >
              <input
                value={renameValue}
                onChange={(event) => setRenameValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    cancelRename();
                  }
                }}
                autoFocus
                maxLength={80}
                aria-label={`重命名 ${session.title}`}
              />
            </form>
          ) : (
            <button type="button" className="history-item-main" onClick={() => onSelect(session.id)}>
              <span>{session.title}</span>
              <time>{sessionTime(session.updatedAt)}</time>
            </button>
          )}
          <button
            type="button"
            className="history-more"
            aria-label={`管理 ${session.title}`}
            aria-expanded={historyMenuId === session.id}
            onClick={(e) => (historyMenuId === session.id ? setHistoryMenuId(null) : openMenu(session.id, e))}
          >
            <MoreHorizontalIcon />
          </button>
        </div>
      ))}
      {historyMenuId && menuPosition && (
        <Portal>
          <div
            className="history-menu"
            role="menu"
            style={{
              top: `${menuPosition.top}px`,
              left: `${menuPosition.left}px`,
            }}
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                const session = sessions.find((s) => s.id === historyMenuId);
                if (session) beginRename(session);
              }}
            >
              <PencilIcon />
              <span>重命名</span>
            </button>
            <button
              type="button"
              role="menuitem"
              className="history-menu-danger"
              onClick={() => {
                const session = sessions.find((s) => s.id === historyMenuId);
                setHistoryMenuId(null);
                setMenuPosition(null);
                if (session) void onDelete(session);
              }}
            >
              <TrashIcon />
              <span>删除</span>
            </button>
          </div>
        </Portal>
      )}
    </>
  );
}

export function ChatWorkspace({ initialSessionId = null }: { initialSessionId?: string | null }) {
  const router = useRouter();
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [files, setFiles] = useState<SessionFile[]>([]);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>(MODELS);
  const [selectedModel, setSelectedModel] = useState(MODELS[0]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [referenceSources, setReferenceSources] = useState<ReferenceSource[]>([]);
  const [clientId] = useState(() => typeof window === "undefined" ? "" : getClientId());
  const [confirmDelete, setConfirmDelete] = useState<Session | null>(null);

  const refreshSessions = useCallback(async () => {
    if (!clientId) return;
    try {
      const data = await fetch("/api/sessions", {
        headers: { "x-luma-client-id": clientId },
      }).then((r) => r.json()) as { sessions?: Session[] };
      setSessions(Array.isArray(data.sessions) ? data.sessions : []);
    } catch {
      // The current conversation can continue if the sidebar refresh fails.
    }
  }, [clientId]);

  const refreshSessionFiles = useCallback(async (id: string) => {
    if (!clientId) return;
    try {
      const data = await fetch(`/api/sessions/${id}`, {
        headers: { "x-luma-client-id": clientId },
      }).then((r) => r.json()) as { files?: SessionFile[] };
      setFiles(Array.isArray(data.files) ? data.files : []);
    } catch {
      // Generated files can be picked up on the next session load.
    }
  }, [clientId]);

  const adapter = useMemo(
    () =>
      createChatModelAdapter({
        sessionId,
        modelId: selectedModel.id,
        clientId,
        onSessionCreated: (id) => {
          setSessionId(id);
          window.history.replaceState(null, "", `/chat/${id}`);
        },
        onComplete: async (id) => {
          await Promise.all([refreshSessions(), refreshSessionFiles(id)]);
        },
        onError: (message) => setError(message),
      }),
    [clientId, refreshSessionFiles, refreshSessions, sessionId, selectedModel.id]
  );

  const runtime = useLocalRuntime(adapter);
  const runtimeRef = useRef(runtime);

  useEffect(() => {
    runtimeRef.current = runtime;
  }, [runtime]);

  useEffect(() => {
    if (!clientId) return;
    queueMicrotask(async () => {
      try {
        const [sessionData, modelData, sourceData] = await Promise.all([
          fetch("/api/sessions", {
            headers: { "x-luma-client-id": clientId },
          }).then((r) => r.json()) as Promise<{ sessions?: Session[] }>,
          fetch("/api/models", {
            headers: { "x-luma-client-id": clientId },
          }).then((r) => r.json()) as Promise<{ models?: string[] }>,
          fetch("/api/sources", {
            headers: { "x-luma-client-id": clientId },
          }).then((r) => r.json()) as Promise<{ sources?: ReferenceSource[] }>,
        ]);
        setSessions(Array.isArray(sessionData.sessions) ? sessionData.sessions : []);
        const options = (Array.isArray(modelData.models) ? modelData.models : []).map(
          (id) => MODELS.find((model) => model.id === id) || { id, modality: "text" as const }
        );
        if (options.length) {
          setModelOptions(options);
          setSelectedModel((current) => options.some((model) => model.id === current.id) ? current : options[0]);
        }
        setReferenceSources(Array.isArray(sourceData.sources) ? sourceData.sources : []);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "无法初始化工作区");
      }
    });
  }, [clientId]);

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    queueMicrotask(async () => {
      if (!initialSessionId) {
        setSessionId(null);
        setFiles([]);
        runtimeRef.current.thread.reset([]);
        return;
      }

      setSessionId(initialSessionId);
      setError(null);
      try {
        const data = await fetch(`/api/sessions/${initialSessionId}`, {
          headers: { "x-luma-client-id": clientId },
        }).then((r) => r.json()) as { session: Session; messages: PersistedMessage[]; files: SessionFile[] };
        if (cancelled) return;
        setFiles(data.files);
        setSelectedModel(
          MODELS.find((model) => model.id === data.session.modelId)
          || { id: data.session.modelId, modality: "text" }
        );
        runtimeRef.current.thread.reset(persistedMessagesToThreadMessages(data.messages));
      } catch (caught) {
        if (cancelled) return;
        setFiles([]);
        runtimeRef.current.thread.reset([]);
        setError(caught instanceof Error ? caught.message : "无法载入会话");
      }
    });
    return () => { cancelled = true; };
  }, [clientId, initialSessionId]);

  useEffect(() => {
    if (!preview) return;
    function handlePreviewKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setPreview(null);
    }
    document.addEventListener("keydown", handlePreviewKeyDown);
    return () => document.removeEventListener("keydown", handlePreviewKeyDown);
  }, [preview]);

  async function resetChat() {
    setSessionId(null);
    setFiles([]);
    setError(null);
    runtime.thread.reset([]);
    router.push("/");
  }

  async function renameSession(session: Session, title: string) {
    try {
      const response = await fetch(`/api/sessions/${session.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "x-luma-client-id": clientId,
        },
        body: JSON.stringify({ title }),
      });
      if (!response.ok) throw new Error("重命名失败");
      setSessions((current) => current.map((item) => item.id === session.id ? { ...item, title, updatedAt: Date.now() } : item));
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "重命名失败");
      return false;
    }
  }

  async function deleteSession(session: Session) {
    setConfirmDelete(session);
  }

  async function confirmDeleteSession() {
    if (!confirmDelete) return;
    try {
      const response = await fetch(`/api/sessions/${confirmDelete.id}`, {
        method: "DELETE",
        headers: { "x-luma-client-id": clientId },
      });
      if (!response.ok) throw new Error("删除失败");
      setSessions((current) => current.filter((item) => item.id !== confirmDelete.id));
      if (confirmDelete.id === sessionId) {
        setSessionId(null);
        setFiles([]);
        runtimeRef.current.thread.reset([]);
        router.push("/");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败");
    } finally {
      setConfirmDelete(null);
    }
  }

  async function selectModel(model: ModelOption) {
    setSelectedModel(model);
    if (sessionId) {
      await fetch(`/api/sessions/${sessionId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "x-luma-client-id": clientId,
        },
        body: JSON.stringify({ modelId: model.id }),
      });
      setSessions((current) =>
        current.map((session) =>
          session.id === sessionId ? { ...session, modelId: model.id, updatedAt: Date.now() } : session
        )
      );
    }
  }

  async function uploadFile(upload: File) {
    if (upload.size > 10 * 1024 * 1024) {
      setError("单个文件不能超过 10 MB");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      let activeId = sessionId;
      if (!activeId) {
        const response = await fetch("/api/sessions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-luma-client-id": clientId,
          },
          body: JSON.stringify({ modelId: selectedModel.id }),
        });
        const data = await response.json() as { session: Session };
        activeId = data.session.id;
        setSessionId(activeId);
        window.history.replaceState(null, "", `/chat/${activeId}`);
        await refreshSessions();
      }

      const form = new FormData();
      form.append("file", upload);
      const data = await fetch(`/api/sessions/${activeId}/files`, {
        method: "POST",
        headers: { "x-luma-client-id": clientId },
        body: form,
      }).then((r) => r.json()) as { file: SessionFile };
      setFiles((current) => [...current, data.file]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function openPreview(file: SessionFile) {
    const textLike = file.contentType.startsWith("text/")
      || file.contentType === "application/json"
      || file.contentType === "application/javascript"
      || /\.(md|markdown|json|csv|log|txt|xml|yaml|yml|ts|tsx|js|jsx|css|html)$/i.test(file.name);

    if (!textLike) {
      setPreview({ file });
      return;
    }

    try {
      const response = await fetch(file.url);
      if (!response.ok) throw new Error("文件读取失败");
      setPreview({ file, text: await response.text() });
    } catch {
      setError("文件预览失败");
    }
  }

  const activeSession = sessionId ? sessions.find((session) => session.id === sessionId) : null;

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="app-shell" data-history-open={historyOpen} data-sidebar-collapsed={sidebarCollapsed}>
        <aside className="rail" aria-label="历史会话">
          <div className="rail-head">
            <button
              className="sidebar-toggle"
              onClick={() => setSidebarCollapsed((value) => !value)}
              aria-label={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
            >
              <MenuIcon />
            </button>
            {!sidebarCollapsed && <div className="brand-copy"><strong>{BRAND.displayName}</strong></div>}
          </div>
          <button className="rail-button" onClick={resetChat} aria-label="新建对话">
            <PlusIcon />
            {!sidebarCollapsed && <span>新建会话</span>}
          </button>
          {!sidebarCollapsed && (
            <div className="history-list">
              <div className="history-label"><span>最近会话</span><b>{sessions.length}</b></div>
              <HistoryList
                sessions={sessions}
                activeSessionId={sessionId}
                onSelect={(id) => {
                  setHistoryOpen(false);
                  router.push(`/chat/${id}`);
                }}
                onRename={renameSession}
                onDelete={deleteSession}
              />
            </div>
          )}
          <div className="rail-spacer" />
          <button className="rail-stats" onClick={() => router.push("/stats")} aria-label="用量统计">
            <StatsIcon />
            {!sidebarCollapsed && <span>用量统计</span>}
          </button>
          {!sidebarCollapsed && (
            <div className="rail-foot">
              <span className="connection-dot" />
              <small>Agent 已连接</small>
            </div>
          )}
        </aside>

        <section className="workspace">
          <header className="topbar">
            <button
              className="history-toggle"
              onClick={() => setHistoryOpen((value) => !value)}
              aria-label="打开历史会话"
            >
              <span />
              <span />
              <span />
            </button>
            <div className="topbar-context">
              <strong>{activeSession?.title || "新会话"}</strong>
            </div>
          </header>

          <div className="conversation" aria-live="polite">
            {files.length > 0 && (
              <section className="session-files" aria-label="会话文件">
                <div className="file-section-head">
                  <span>会话文件</span>
                  <b>{files.length}</b>
                </div>
                <div className="file-grid">
                  {files.map((file) => (
                    <div key={file.id} className="file-card-wrapper">
                      <button
                        type="button"
                        className="file-card"
                        onClick={() => void openPreview(file)}
                        aria-label={`预览 ${file.name}`}
                      >
                        <span className="file-type">{file.name.split(".").pop()?.slice(0, 4).toUpperCase() || "FILE"}</span>
                        <span className="file-info">
                          <strong>{file.name}</strong>
                          <small>{formatBytes(file.size)}</small>
                        </span>
                      </button>
                      <a
                        href={file.url}
                        download={file.name}
                        className="file-download-btn"
                        title={`下载 ${file.name}`}
                        aria-label={`下载 ${file.name}`}
                      >
                        <DownloadIcon />
                      </a>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {!sessionId && files.length === 0 && (
              <section className="empty-state" aria-label="新会话">
                <span className="empty-track" aria-hidden="true" />
                <h1>今天要完成什么？</h1>
              </section>
            )}

            <ThreadPrimitive.Root>
              <ThreadPrimitive.Viewport>
                <ThreadPrimitive.Messages
                  components={{
                    UserMessage: () => (
                      <article className="message message-user">
                        <div className="message-label">你</div>
                        <CustomMessage />
                      </article>
                    ),
                    AssistantMessage: () => (
                      <article className="message message-assistant">
                        <div className="message-label">{selectedModel.id}</div>
                        <CustomMessage />
                      </article>
                    ),
                  }}
                />
              </ThreadPrimitive.Viewport>
            </ThreadPrimitive.Root>
          </div>

          <div className="composer-zone">
            {error && (
              <div className="inline-error" role="alert">
                {error}
                <button onClick={() => setError(null)}>关闭</button>
              </div>
            )}
            <div className="composer">
              <CustomComposer
                referenceSources={referenceSources}
                clientId={clientId}
                onFileUpload={uploadFile}
                uploading={uploading}
                modelOptions={modelOptions}
                selectedModel={selectedModel}
                onModelSelect={selectModel}
              />
            </div>
          </div>

          <ThemeToggle />
        </section>

        {historyOpen && (
          <button className="history-backdrop" onClick={() => setHistoryOpen(false)} aria-label="关闭历史会话" />
        )}

        {preview && (
          <div
            className="preview-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setPreview(null);
            }}
          >
            <section className="preview-panel" role="dialog" aria-modal="true" aria-label={`预览 ${preview.file.name}`}>
              <header>
                <div>
                  <strong>{preview.file.name}</strong>
                  <span>{formatBytes(preview.file.size)} · {preview.file.contentType}</span>
                </div>
                <div>
                  <a href={preview.file.url} download={preview.file.name}>下载</a>
                  <button type="button" onClick={() => setPreview(null)} aria-label="关闭预览">关闭</button>
                </div>
              </header>
              <div className="preview-content">
                {preview.file.contentType.startsWith("image/") ? (
                  <object data={preview.file.url} type={preview.file.contentType} aria-label={preview.file.name} />
                ) : preview.file.contentType === "application/pdf" ? (
                  <iframe src={preview.file.url} title={preview.file.name} />
                ) : preview.text !== undefined ? (
                  <pre>{preview.text}</pre>
                ) : (
                  <div className="generic-preview">
                    <span>{preview.file.name.split(".").pop()?.toUpperCase() || "FILE"}</span>
                    <p>此文件类型暂不支持内嵌预览。</p>
                    <a href={preview.file.url} download={preview.file.name}>下载文件</a>
                  </div>
                )}
              </div>
            </section>
          </div>
        )}

        {confirmDelete && (
          <ConfirmDialog
            title="删除会话"
            message={`确定删除"${confirmDelete.title}"吗？删除后无法恢复。`}
            confirmText="删除"
            cancelText="取消"
            variant="danger"
            onConfirm={confirmDeleteSession}
            onCancel={() => setConfirmDelete(null)}
          />
        )}
      </main>
    </AssistantRuntimeProvider>
  );
}
