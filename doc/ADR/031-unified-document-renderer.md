# ADR-031: 统一无桌面文档渲染引擎

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-18 |
| 决策状态 | 已采纳 |
| 实现状态 | 组件与局部平台链路已验证，整篇报告未验收 |
| 替代的旧 ADR | [ADR-029](029-native-office-document-tools.md)的WPS回退与渲染部署选择 |
| 被哪份 ADR 替代 | 无 |

## 背景

Windows WPS对平台稿件连续两次超时180秒。Linux旧LibreOffice可转换，但新增中文缺字：模板嵌入字体子集，新增用字不在子集中，系统字体别名不能覆盖这些内嵌字体。

## 决策与实测

- 保留OfficeCLI原生MCP编辑，统一LibreOffice无桌面渲染及PDFium阅读。用Debian维护的25.2包替换7.4；Linux运行时直接使用，Windows使用同一Docker构建的document-renderer目标。PDFium Python包升级5.13，避免4.30在PDF阅读工作线程中急切加载非必要NumPy；真实Run定位到该原生导入卡住，新增线程回归覆盖。
- 在临时渲染副本中解除明确标记subsetted的字体引用，保留原模板、正文和样式；镜像提供完整Noto CJK和Liberation字体。每次独立Office进程及用户配置，失败不发布半成品。
- 同一平台稿件：旧7.4加字体别名13.79秒、78页，仍缺字；25.2解除字体子集后13.53秒、74页，正文文字、40表、4分节及媒体内容保留，抽查新增正文与合并表格无缺字。耗时仅为单次组件测试，不是整篇撰写耗时。
- 正式Windows到Docker链路15.20秒完成同稿；故意缓存为999的中文目录样例8.41秒刷新为实际第2、4页。原模板不变；原稿没有真实目录字段时返回not_present，不伪称已生成目录。
- 实际平台局部撰写358.81秒、51次工具调用，写入769字并发布DOCX/PDF；渲染13.085秒，两次PDF读取0.105/0.192秒，7次固定查询无参数错误或重复查询，1次学校范围查询被拒绝。正文旧校名与百分比跨行仍有遗留，不代表整篇内容/版式验收通过。199项测试通过；Docker内199项通过（跳过3项），另16项部署检查通过。
- [ONLYOFFICE Builder 9.4](https://api.onlyoffice.com/docs/document-builder/get-started/installing/)独立Windows包实跑8.86秒、68页，但PDF有明显试用水印，日志license is invalid；不采用。无需完整DocumentServer即可独立运行，纠正先前调研结论。
- [Aspose.Words](https://docs.aspose.com/words/python-net/licensing/)免费版有水印与长文限制，用户明确排除后停止，未运行对比。Gotenberg/unoserver仍依赖LibreOffice，不为本地转换另加HTTP服务。HTML/Markdown解析不能替代原DOCX分页。
- 删除WPS/pywin32及候选SDK，不保留多引擎回退或厂商插件。仅保留通用渲染复测脚本，不引入模板专用生成程序。

## 后果

Windows开发需要Docker；Linux部署不需要Docker-in-Docker或桌面Office。字体替代可能改变分页，必须检查最终PDF；渲染成功不代表报告事实、目录存在性或全文撰写验收通过。

## 工程要求检查

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | 渲染容器禁网且不注入业务Token/模型密钥；原有真实Java链路差距保留 |
| REQ-002 | 部分满足 | 复用原Capability、模板授权和Artifact边界；本次不解决Agent生产沙箱及Java授权差距 |
