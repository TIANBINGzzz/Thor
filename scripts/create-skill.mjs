#!/usr/bin/env node

import { readdir, writeFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import readline from "node:readline";

const PROJECT_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SKILLS_DIR = join(PROJECT_ROOT, ".claude", "skills");

function createInterface() {
  return readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
}

function question(rl, prompt) {
  return new Promise((resolve) => {
    rl.question(prompt, (answer) => {
      resolve(answer.trim());
    });
  });
}

function validateSkillName(name) {
  if (!name) {
    return "Skill 名称不能为空";
  }
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(name)) {
    return "Skill 名称只能包含小写字母、数字和连字符，且不能以连字符开头或结尾";
  }
  return null;
}

async function checkSkillExists(name) {
  try {
    const entries = await readdir(SKILLS_DIR, { withFileTypes: true });
    return entries.some((entry) => entry.isDirectory() && entry.name === name);
  } catch {
    return false;
  }
}

function generateSkillContent(name, description, scenarios, workflow) {
  return `---
name: ${name}
description: ${description}
---

# ${name.split("-").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ")}

${description}

## 使用场景

${scenarios || "描述什么情况下使用这个 Skill"}

## 工作流程

${workflow || "1. 第一步\n2. 第二步\n3. 第三步"}

## 规则

- 遵循项目约定和最佳实践
- 明确说明假设和限制
- 提供可验证的输出

## 示例

（可选）展示具体的使用示例
`;
}

async function main() {
  const rl = createInterface();

  console.log("🎯 Skill Creator - 交互式创建向导\n");

  try {
    // 1. 获取 Skill 名称
    let skillName;
    while (true) {
      skillName = await question(rl, "📝 Skill 名称（kebab-case，如 api-test）: ");
      const error = validateSkillName(skillName);
      if (error) {
        console.log(`❌ ${error}\n`);
        continue;
      }

      const exists = await checkSkillExists(skillName);
      if (exists) {
        console.log(`❌ Skill "${skillName}" 已存在\n`);
        continue;
      }

      break;
    }

    // 2. 获取描述
    const description = await question(rl, "📄 一句话描述（用途）: ");
    if (!description) {
      console.log("❌ 描述不能为空");
      rl.close();
      return;
    }

    // 3. 获取使用场景
    const scenarios = await question(rl, "🎬 使用场景（什么时候用）: ");

    // 4. 获取工作流程（可选）
    console.log("\n💡 工作流程（可选，直接回车跳过）:");
    console.log("   输入步骤，每行一个，输入空行结束");
    const workflowSteps = [];
    let stepNum = 1;
    while (true) {
      const step = await question(rl, `   ${stepNum}. `);
      if (!step) break;
      workflowSteps.push(step);
      stepNum++;
    }
    const workflow = workflowSteps.length
      ? workflowSteps.map((step, i) => `${i + 1}. ${step}`).join("\n")
      : null;

    // 5. 预览
    console.log("\n" + "=".repeat(60));
    console.log("📋 预览:");
    console.log("=".repeat(60));
    console.log(generateSkillContent(skillName, description, scenarios, workflow));
    console.log("=".repeat(60));

    // 6. 确认
    const confirm = await question(rl, "\n✅ 确认创建？(yes/no): ");
    if (confirm.toLowerCase() !== "yes" && confirm.toLowerCase() !== "y") {
      console.log("❌ 已取消");
      rl.close();
      return;
    }

    // 7. 创建文件
    const skillDir = join(SKILLS_DIR, skillName);
    const skillFile = join(skillDir, "SKILL.md");

    await mkdir(skillDir, { recursive: true });
    await writeFile(
      skillFile,
      generateSkillContent(skillName, description, scenarios, workflow),
      "utf8",
    );

    console.log("\n🎉 成功！");
    console.log(`📁 文件位置: .claude/skills/${skillName}/SKILL.md`);
    console.log(`🔗 引用方式: @skill:${skillName}`);
    console.log(`\n💡 提示: 你可以继续编辑 SKILL.md 文件来完善内容`);
  } catch (error) {
    console.error("\n❌ 错误:", error.message);
  } finally {
    rl.close();
  }
}

main();
