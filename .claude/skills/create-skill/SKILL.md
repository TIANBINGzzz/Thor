---
name: create-skill
description: 交互式引导创建新的 Skill，自动生成规范的目录结构和 SKILL.md 文件
---

# 创建 Skill

引导用户创建新的 Skill，确保格式规范。

## 工作流程

1. **询问基本信息**
   - Skill 名称（kebab-case，如 `api-test`）
   - 一句话描述（用于 frontmatter）
   - 使用场景（什么时候用这个 skill）

2. **验证名称**
   - 检查是否已存在同名 skill
   - 验证名称格式（只能用小写字母、数字、连字符）

3. **生成文件结构**
   ```
   .claude/skills/
   └── <skill-name>/
       └── SKILL.md
   ```

4. **生成 SKILL.md 模板**
   ```markdown
   ---
   name: <skill-name>
   description: <用户输入的描述>
   ---

   # <Skill 标题>

   <简短介绍>

   ## 使用场景

   <用户输入的场景>

   ## 工作流程

   1. 第一步
   2. 第二步
   3. 第三步

   ## 规则

   - 规则 1
   - 规则 2

   ## 示例

   （可选）展示使用示例
   ```

5. **确认并保存**
   - 显示生成的内容预览
   - 询问是否保存
   - 保存后提示可以使用 `@skill:<name>` 引用

## 交互示例

```
我: 帮我创建一个新的 skill

Claude: 好的！我来帮你创建一个新的 Skill。

请告诉我：
1. Skill 名称（使用 kebab-case，如 api-test）
2. 一句话描述这个 Skill 的用途
3. 什么场景下会使用这个 Skill

我: 
1. database-migration
2. 管理和执行数据库迁移脚本
3. 需要升级数据库 schema、添加字段、修改表结构时

Claude: 好的！我将创建以下 Skill：

名称: database-migration
描述: 管理和执行数据库迁移脚本
场景: 需要升级数据库 schema、添加字段、修改表结构时

[显示完整的 SKILL.md 内容]

确认创建吗？(yes/no)

我: yes

Claude: ✅ Skill 已创建！
文件位置: .claude/skills/database-migration/SKILL.md
可以使用 @skill:database-migration 引用这个 Skill
```

## 验证规则

- **名称格式**: 只能包含小写字母、数字、连字符
- **名称唯一性**: 不能与现有 skill 重名
- **描述长度**: 建议不超过 100 字
- **必需字段**: name 和 description 必须填写

## 后续建议

创建后可以：
- 使用 Read 工具查看生成的文件
- 使用 Edit 工具完善内容
- 添加 references/ 子目录存放参考文档
- 在对话中测试使用场景

## 注意事项

- 不要在名称中使用空格或大写字母
- 描述要简洁明确，方便在 @ 引用时识别
- 工作流程要具体可执行，避免模糊表述
