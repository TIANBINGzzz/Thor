/**
 * 品牌配置 - 统一管理所有平台名称和标识。
 * Web package 使用 ESM，因此这里必须保持 ESM 导出。
 */
const brandConfig = {
  // 项目名称
  name: "Thor",

  // 显示名称（用户界面显示）
  displayName: "Thor AI",

  // 描述
  description: "智能对话助手，支持多模型切换和文件交互",

  // 短描述
  tagline: "AI 对话助手",

  // 公司/组织
  organization: "CCSDKScribe",

  // 版本
  version: "1.0.0",

  // API 相关（内部使用，改动需谨慎）
  api: {
    clientIdHeader: "x-luma-client-id", // 保持不变，避免破坏现有 API
    clientIdKey: "luma-client-id",       // 保持不变，避免破坏现有存储
  },
};

export default brandConfig;
