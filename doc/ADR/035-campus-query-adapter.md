# ADR-035: 校园问数的受控 MCP 适配

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-23 |
| 决策状态 | 已采纳 |
| 实现状态 | Python 已实现；真实链路曾验证，当前优化用模拟取数对照，Java生产授权未验收 |
| 最近核对 | 2026-09-23 |
| 替代的旧 ADR | 无 |
| 被哪份 ADR 替代 | 无 |

## 背景
校园 MCP 要求顶层 `user_context_token`；仅 Authorization 实测返回身份错误。用户确认该字段就是业务 Token，并授权按此继续实现。

## 决策
- 新增 campus-brain-query Capability，复用现有 Agent/会话，不新增 Workflow 或 Java 响应分支，不接入双高数据库。
- 工具 Schema 不暴露 Token；通用 Runtime 的 `MCP_AUTH_RULES.arguments` 在发送请求副本时映射当前 Run 凭据，业务能力不维护 Token 字段。此限定例外同步至 REQ-001；连接通过可信资产中的配置引用交由公共解析器注入，不维护能力专用 Nacos 读取器，见[配置字段](../../config/README.md)，其余静态Header、Schema、学校数量及知识记录由服务端资产确定。
- 每轮绑定凭据、预算和身份；Client 续用时重置，Token 变化仍由既有指纹机制重建 Client。只挂载校园工具，关闭内置工具及隐式 Skill/MCP 发现。
- 仅放行本校与匿名统计字段；原始上游错误不进入模型或日志。请求不重试、不跟随重定向。未来上游改用 Header 时可移除参数绑定，保持业务协议不变。

- 模型 thinking、effort、max_turns 和 prompt_mode 由可信执行资产的 runtime 配置装配，不接受浏览器覆盖；max_turns 仅为轮数上限，不是两阶段编排。SDK省略disabled请求字段时，通过其原生extra body显式关闭思考；不新增供应商代理。校园指令优先选择合理候选并在答案展示全称供用户纠正。

## 后果与验证
- 2026-09-23 真实只读验证：本校身份、预置群体及常模返回成功；7所拒绝，8/11/12所成功，远端描述仍写12。minimum_schools 独立配置默认8，Schema与指令共同读取。
- 详细回归结果及未决边界见[校园验收](../verification/campus-query.md)。Java当前认证上下文、真实授权与撤销、上游日志策略仍需独立验收。

## 工程要求检查
| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | 本轮适配与Token不可见边界；Java、撤销、上游日志未验收 |
| REQ-002 | 部分满足 | Capability及内部资产受控装配；Java生产授权未验收 |
