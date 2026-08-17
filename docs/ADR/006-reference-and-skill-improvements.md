# 006 - 引用系统和 Skill Creator 完善

日期: 2026-08-17  
状态: 已完成

## 背景

- @ 引用选择后无视觉反馈
- Skill Creator 弹窗显示异常（限制在对话框内）
- 消息发送后输入框不清空
- 需要 @skill: 引用类型和创建工具

## 决策

1. 添加 @skill: 引用支持，扫描 .claude/skills/ 目录
2. 引用显示为彩色 chip（⚡ skill 蓝色、📦 pkg 绿色）
3. Skill Creator 用 Portal 渲染到 body
4. 监听表单提交清空输入框
5. 添加粘贴上传功能
6. 创建交互式 skill 生成器（npm run create-skill）

## 后果

### 好处
- 引用有清晰视觉标识，参考 Cursor 设计
- Skill 可被引用和创建，降低门槛
- 输入框行为符合预期
- 文件上传体验更好

### 代价
- 新增 ReferenceChips.tsx 和 Portal.tsx 组件
- references.mjs 增加 skill 数据源

### 风险
- skill 数量过多时加载性能（30 秒缓存缓解）
