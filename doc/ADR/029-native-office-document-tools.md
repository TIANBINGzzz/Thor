# ADR-029: 原生Office文档工具与模型自主撰写

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-18 |
| 决策状态 | 已采纳 |
| 实现状态 | 部分实现 |
| 最近核对 | 2026-09-18 |
| 替代的旧 ADR | 替代 ADR-026 的地图维护及 ADR-027 的自有 DOCX 工具；旧正文见[历史索引](README.md#已移除的正文)，自主撰写和可信上下文保留 |
| 被哪份 ADR 替代 | [ADR-031](031-unified-document-renderer.md)替代WPS回退及渲染部署选择；原生编辑和模型自主撰写保留 |

## 背景

用户要求提供成熟、通用的文档工具，由模型决定如何读取材料、规划查询、组织正文及检查成稿；旧地图、批量计划和自有编辑层增加维护成本。

## 决策

- 直接挂载[iOfficeAI/OfficeCLI](https://github.com/iOfficeAI/OfficeCLI)原生MCP（Apache-2.0，固定1.0.151），使用通用命令读取和编辑，不自研编辑器或再包装专用报告操作。版本活跃但项目年轻，升级须重新做原模板回写验收。
- [MarkItDown](https://github.com/microsoft/markitdown)、[Docling](https://github.com/docling-project/docling)、[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)偏材料解析/OCR，不能替代原DOCX编辑；本轮与已有读取重叠，不引入。Mammoth/HTML往返存在样式损失；Open XML SDK/docx4j仍需自建操作层；ONLYOFFICE独立Builder的后续实测见ADR-031。
- OfficeCLI读取Office材料；最初采用LibreOffice或Windows WPS刷新字段，后由ADR-031统一为LibreOffice；PDFium提供分页文字及图像核验。
- 预制、上传及无模板共用 document-writing 和 writing-docx；共同规则由 instructions.md 显式注入，预制模板仅额外加载所选指南与参考 DOCX。模型自主规划、取证、撰写和检查，不引入报告状态机、固定段落流水线或强制草稿字段；传值见[模板契约](../specs/ccsdk-runtime-interface.md#34-业务-payload)。
- 删除位置地图、固定取数计划和维护生成器；保留原DOCX、逐页来源知识、指标SQL、可信模板装配、来源授权及Artifact文件边界。
- 可选生图用[Qwen Image 3.0](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)的OpenAI Images接口和现有httpx；单个images工具支持生成及参考图编辑，共同规则按需引导，不新增单工具Skill。密钥仅留Worker闭包，生成图不能充当真实成果证据。

## 实现证据与差距

- 工具装配见`python/runtime/config.py`，渲染/PDF入口见`python/tools/documents.py`及`document_conversion.py`；模板仅登记DOCX与指南。
- 2026-09-18：166项回归通过（Linux跳过2项）；原40表回写保留结构/样式/媒体，WPS及Linux LibreOffice目录分页实测通过；Qwen Image 3.0真实平台生图发布51.7秒。整篇报告25分28秒触达100轮，未发布，成稿验收失败，不能据此宣称提速。
- 原生MCP拥有进程可访问的文件权限；当前bypassPermissions、工作目录约定及容器均不构成生产租户沙箱。

## 后果

- 好处：复用维护中的Office工具，模板变更无需同步地图或报告代码。
- 代价：部署需OfficeCLI和实际Office渲染引擎；模型承担步骤选择与检查责任。
- 风险：复杂版式、目录及事实仍可能不正确；工具成功与Artifact发布不能替代实际成稿验收。

## 工程要求检查

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | 新工具登记为不接业务Token，装配测试验证仅business接收Token；真实Java凭据链路差距保留 |
| REQ-002 | 部分满足 | 沿用已授权Capability、可信模板/来源及内部工具装配，外部字段不变；Java授权和生产沙箱未验收 |

## 状态变更记录

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-18 | 已采纳 | 部分实现 | 工具及生图已实测，整篇撰写仍受模型重复取证和只标缺口不写正文影响 |
