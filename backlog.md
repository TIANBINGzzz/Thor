# 待办与背景

记录**已判明原因、但尚未实施**的问题。每条写清背景、当前状态和待做动作，目的是避免同一个问题被反复重新诊断。

- `readme.md` 描述项目**现在是什么**，以及已经生效的设计。
- 本文件描述**已知要改什么、为什么这样改**，以及明确决定暂不做的事。
- 一条待办落地后，把结论并入 `readme.md`，并从本文件删除，不留历史记录。

---

## 1. 权限隔离：Bash 是逃生舱

**背景**

当前入口是 `permissionMode: "bypassPermissions"` 加完整 Claude Code 工具集。给 `Read` / `Write` / `Edit` 单独加路径校验并不构成边界——模型可以用 `Bash` 绕过全部文件工具限制。这不是推测：会话 `68b42b5f…` 里模型自行执行了 `npm install docx`，并在项目根写出文件，全程没有任何拦截。

因此权限隔离的顺序是**先定 Bash 策略，再谈路径校验**。反过来做只是提高绕过门槛。

**已决定方向：容器 / 沙箱限制工作目录**

把 agent 跑在容器里，挂载策略为：

```text
/workspace/session/<id>   → 可读写
/workspace/project        → 只读
其余                       → 不挂载
```

选它的理由是边界由内核保证，不依赖命令解析。命令前缀白名单在管道、子 shell 和 `eval` 前都会失效，属于过渡手段；完全禁用 `Bash` 则会砍掉 `node` 执行和 `npm view` 取真实数据的能力，报告类任务明显受限。按"架构决策往长了做"的约束，直接选最终形态。

**待做**

- 确定容器运行时与镜像，以及本机开发流程如何适配（当前 `npm run ui` 是裸进程）。
- 挂载与会话目录生命周期对齐 `.scribe-sessions/<id>/`。
- 容器落地后，`canUseTool` 的文件路径校验作为第二道防线补上，而不是唯一防线。

**明确不做**

本轮不做任何权限相关改动。命令前缀白名单不实施。

---

## 2. 产物位置目前只有软约束

**背景**

`python/local/sessions.py` 的 `session_prompt_context()` 现在无条件下发会话目录和"产物必须写在该目录内"的约束，修好了此前"未上传文件时不告知目录、模型把报告写到项目根"的问题，并有回归测试覆盖。

但这是 **prompt 层的软约束**。在 `bypassPermissions` 下模型仍然可以写到任意位置，只是不再因为缺少信息而写错。

**待做**

真实边界依赖第 1 项。第 1 项落地前，不要把当前状态当作已隔离。

---

## 3. WebFetch 失败原因已查明，代理配置已修复

**背景**

会话 `68b42b5f…` 里两次 `WebFetch` 失败，此前被我错误归因为"网关限制"。curl 实测是两个互不相关的原因：

| 目标 | curl 结果 | 结论 |
| --- | --- | --- |
| Purdue OWL 链接 | `404`，2.6s | 模型编造或已失效的 URL |
| `en.wikipedia.org:443` | `curl: (28)`，21s 超时 | 本机连不上该站点 |

关键区别：`WebFetch` 是**客户端工具**，由 CLI 在本机直接发请求，不经过 Qwen 网关。所以"让 WebFetch 复用 Qwen 自带联网搜索"这个方向在分层上不成立——那是服务端搜索，两者不在同一层。真正要做的是接独立搜索 MCP（`readme.md` 后续执行计划第 7 项）。

`WebSearch` 在当前网关伪造成功是另一件事，已通过 `disallowedTools` 处理，结论不变。

**已修复**

`claude.exe` 不读 Windows 系统代理，只认 `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` 环境变量。已在 `.env` / `.env.example` 里补齐代理配置和注释，并实测 Wikipedia 通过。

`NO_PROXY` 必须排除百炼网关（`.aliyuncs.com`），否则国内直连流量会被绕出去。

Python worker 的 system prompt 补充"WebFetch 可用但只能抓取已知 URL，不能用来搜索或发现网页，禁止猜测 URL"，避免模型重复 404 + 当成"查过了"的错误。

**不再需要**

- 扩大本机可达性探测：已用 Wikipedia 验证代理工作，模式清楚。
- 网关搜索参数探测：`WebFetch` 不经网关，探测方向不成立。

---

## 4. 模型主动请求选择（引用方案 B）

**背景**

用户主动选（方案 A）已落地，见 `readme.md`"引用语法与大候选集"。缺的是反方向：模型执行到一半发现缺参数，需要**它主动要求用户选一项**。

机制已确认存在。`sdk.d.ts` 的 `PermissionResult` 是：

```ts
{ behavior: 'allow', updatedInput?: Record<string, unknown> }
```

`canUseTool` 在工具执行前被调用，且可以改写入参。所以链路是：模型带空值调工具 → `canUseTool` 截住 → 推 SSE 事件给浏览器（只带 source 标识，不带候选项）→ 前端弹现成的选择面板 → 用户选完回传 → `canUseTool` 用 `updatedInput` 把真值塞回去 → 工具执行。模型全程没见过候选集。

**待做**

现在 `handleChat` 是单向的：`emit` 只能服务端 → 浏览器，SSE 流跑完就 `response.end()`。`canUseTool` 返回 Promise，要挂住等用户操作，需要浏览器能往回喂数据——加一个 `POST /api/chat/:id/resolve` 把 pending Promise resolve 掉即可，SSE 协议本身不用改。

复用已有的 `/api/options` 分页接口和 `.picker` 面板，增量只有双向通道那一段。

**和第 1 项的关系**

这条双向通道和工具审批 UI 是同一个机制（审批也是"挂住等用户点"）。两件事一起做，通道只建一次。

---

## 5. `.tmp/` 里还有跨会话残留

第 1 项落地前，模型仍会往 `.tmp/` 写脚本。目前留有 `.tmp/build_brief_docx.mjs` 等文件，其中硬编码了另一个会话的目录路径（`533bcb26…`）。`.tmp/` 已在 `.gitignore` 里，不会提交，但它和会话目录一样属于没有隔离的可写位置。

容器方案落地时把 `.tmp/` 一并纳入挂载策略，否则它会变成绕过会话隔离的后门。
