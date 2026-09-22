# ADR-031: 统一无桌面文档渲染引擎

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-18 |
| 决策状态 | 已采纳 |
| 实现状态 | 渲染与修订稿已验证；自主整稿业务质量未验收 |
| 最近核对 | 2026-09-22（合并历史验证边界） |
| 替代的旧 ADR | [029](029-native-office-document-tools.md) 的 WPS 回退及渲染部署选择 |
| 被哪份 ADR 替代 | 无 |

## 背景
Windows WPS 曾连续超时；旧 LibreOffice 的字体子集使新增中文缺字，单加字体别名未解决。

## 决策
- OfficeCLI 原生 MCP 编辑，统一 LibreOffice 无桌面渲染及 PDFium 分页核验；Linux 直接运行，Windows 使用同一 Docker document-renderer 目标，不接桌面 Office 或多引擎回退。
- 临时渲染副本解除明确标记 subsetted 的字体引用，保留原模板/正文/样式；镜像提供完整字体，每次独立 Office 进程与用户配置，失败不发布半成品。
- 渲染更新已有 TOC，不从静态目录推断字段；需要目录而返回 not_present 时必须修复。实际工具与镜像版本以依赖和 Dockerfile 为准。
- ONLYOFFICE Builder 独立包实测有试用水印，Aspose 免费版有水印/长文限制，因此未采用；Gotenberg/unoserver 仍依赖 LibreOffice，不为本地转换另加服务。

## 后果与验证
- 2026-09-18 Linux 与 Windows/Docker 的正文、40 表、4 分节及中文目录刷新测试通过；组件渲染耗时不能当作整篇撰写耗时。
- 历史完整平台稿经七轮修订发布 86 页，已修正所发现目录、表格及期间问题；不代表一次自主生成或正式报送通过。后续真实整稿仍有问题，见 [验收记录](../verification/acceptance.md)。
- Windows 开发需要 Docker，Linux 无需桌面或 Docker-in-Docker；字体替代会影响分页，必须核验实际 PDF，渲染成功不证明事实与目录完整。

## 工程要求检查
| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | 渲染容器禁网且不注入业务/模型密钥；真实 Java 链路差距保留 |
| REQ-002 | 部分满足 | 复用 Capability/模板/成果边界；生产沙箱、Java ACL 和整稿质量另验收 |
