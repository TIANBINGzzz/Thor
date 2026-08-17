# Assistant UI 集成规范

## 核心原则

**不要与 assistant-ui 的内部状态竞争。它管理消息历史和输入框，我们只管理业务状态（会话、文件、模型）。**

## 关键约束

### 1. Adapter 必须记忆化
```tsx
// ✅ 正确：使用 useMemo，避免每次渲染重新创建
const adapter = useMemo(
  () => createChatModelAdapter({ sessionId, modelId, ... }),
  [sessionId, modelId]  // 只在这些变化时重建
);
```

```tsx
// ❌ 错误：每次渲染都创建新 adapter，导致流式响应中断
const adapter = createChatModelAdapter({ sessionId, modelId, ... });
```

### 2. 输入框状态同步
```tsx
// ✅ 正确：受控输入 + MutationObserver 监听清空
const [inputValue, setInputValue] = useState("");

useEffect(() => {
  const textarea = textareaRef.current;
  const observer = new MutationObserver(() => {
    if (textarea.value === "" && inputValue !== "") {
      setInputValue("");  // 同步 assistant-ui 的清空操作
    }
  });
  observer.observe(textarea, { attributes: true });
  return () => observer.disconnect();
}, [inputValue]);

<ComposerPrimitive.Input
  value={inputValue}
  onChange={(e) => setInputValue(e.target.value)}
/>
```

```tsx
// ❌ 错误：完全受控但不监听 assistant-ui 的清空，发送后不清空
<ComposerPrimitive.Input
  value={inputValue}
  onChange={(e) => setInputValue(e.target.value)}
/>
```

### 3. 消息渲染
```tsx
// ✅ 正确：只定制外层结构，内容交给 MessagePrimitive
<ThreadPrimitive.Messages
  components={{
    UserMessage: () => (
      <article className="message">
        <div className="label">你</div>
        <MessagePrimitive.Content />  {/* assistant-ui 处理内容 */}
      </article>
    ),
  }}
/>
```

```tsx
// ❌ 错误：手动从状态读消息，与 assistant-ui 的消息管理冲突
{messages.map(msg => <div>{msg.content}</div>)}
```

### 4. 文件上传集成
```tsx
// ✅ 正确：业务逻辑独立处理，不通过 assistant-ui
<input type="file" onChange={(e) => uploadFile(e.target.files[0])} />

async function uploadFile(file: File) {
  // 直接调用后端 API，更新自己的 files 状态
  const data = await fetch(`/api/sessions/${sessionId}/files`, { ... });
  setFiles(prev => [...prev, data.file]);
}
```

```tsx
// ❌ 错误：尝试把文件塞进 assistant-ui 的消息流
// assistant-ui 不负责文件管理，强行集成会导致状态混乱
```

### 5. 错误处理
```tsx
// ✅ 正确：通过 adapter 的 onError 回调获取错误
const adapter = useMemo(
  () => createChatModelAdapter({
    onError: (message) => setError(message),  // 设置自己的错误状态
  }),
  []
);
```

## 职责划分

| 模块 | assistant-ui 负责 | 我们负责 |
|------|------------------|---------|
| 消息历史 | ✅ 维护、渲染、滚动 | ❌ |
| 输入框 | ✅ 自动清空、发送触发 | ✅ @ 引用补全 |
| 流式响应 | ✅ SSE 解析、增量更新 | ❌ |
| 会话管理 | ❌ | ✅ 创建、切换、列表 |
| 文件上传 | ❌ | ✅ 上传、显示、下载 |
| 模型选择 | ❌ | ✅ 切换、持久化 |
| 错误提示 | ❌ | ✅ 显示、关闭 |

## 常见错误

### 问题：发送后输入框不清空
**原因**：使用受控 `value` 但没有同步 assistant-ui 的内部清空操作  
**解决**：添加 MutationObserver 监听（见上方示例）

### 问题：切换模型后流式响应中断
**原因**：adapter 没有用 useMemo，每次渲染重建  
**解决**：`useMemo(() => createChatModelAdapter(...), [deps])`

### 问题：上传的文件不显示
**原因**：文件不在 assistant-ui 管理范围，必须自己维护 `files` 状态  
**解决**：独立的 `useState<SessionFile[]>` + 自己渲染

### 问题：调试困难，不知道内部发生了什么
**原因**：assistant-ui 是黑盒，状态不可见  
**解决**：添加日志到 adapter 的 `run()` 方法，观察事件流

## 何时不该用 assistant-ui

- 需要完全自定义消息编辑/删除/重试逻辑
- 需要复杂的多模态内容（图片、视频、文件预览）
- 需要离线模式或本地消息缓存
- 团队不熟悉 React 的受控/非受控组件概念

**这些场景下，原生实现反而更简单可控。**
