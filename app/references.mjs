import { readdir, readFile, stat } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * 引用语法：`@<type>:<value>`
 *
 * 前端在 composer 里插入引用，模型只看到这个短标记，候选集永远不进 context。
 * value 里的空白和 `%` 走百分号编码，其余字符（含 `/`、`.`、`-`）保持原样，
 * 这样 `@file:app/public/app.js` 仍然可读，同时解析不会有歧义。
 *
 * 中文标点不是空白，直接跟在引用后面（“看 @file:a.md，然后”）会被吞进 value，
 * 因此显式排除。路径和包名里不会出现这些字符，排掉是安全的。
 */
const REFERENCE_TERMINATORS = "，。、；：！？“”‘’（）《》【】…—～";
const REFERENCE_PATTERN = new RegExp(
  `@([a-z][a-z0-9_]*):([^\\s@${REFERENCE_TERMINATORS}]+)`,
  "g",
);

const PROJECT_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** 项目文件遍历时永远跳过的目录，避免把依赖树和构建产物当成项目内容。 */
const SKIP_DIRECTORIES = new Set([
  "node_modules",
  ".git",
  ".idea",
  ".tmp",
  ".scribe-sessions",
]);

const MAX_LIMIT = 50;
const DEFAULT_LIMIT = 20;
/** 目录树和依赖清单在一次会话里不会变，缓存住，避免每次按键都走磁盘。 */
const CACHE_TTL_MS = 30_000;

/**
 * `@` 也要编码：作用域包名本身以 @ 开头（`@anthropic-ai/sdk`），不编码的话
 * `@pkg:@anthropic-ai/sdk` 会在第二个 @ 处截断。编成 %40 是 URL 里的老惯例。
 */
export function encodeReferenceValue(value) {
  return value.replace(/[%\s@]/g, (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
}

export function decodeReferenceValue(value) {
  return value.replace(/%([0-9a-fA-F]{2})/g, (_, hex) =>
    String.fromCharCode(Number.parseInt(hex, 16)),
  );
}

/** 从 prompt 里抽出所有引用，按出现顺序去重。 */
export function parseReferences(prompt) {
  const found = [];
  const seen = new Set();

  for (const match of String(prompt).matchAll(REFERENCE_PATTERN)) {
    const type = match[1];
    const value = decodeReferenceValue(match[2]);
    const key = `${type}:${value}`;

    if (!seen.has(key)) {
      seen.add(key);
      found.push({ type, value, raw: match[0] });
    }
  }

  return found;
}

function cached(loader) {
  let at = 0;
  let value = null;

  return async () => {
    if (value && Date.now() - at < CACHE_TTL_MS) {
      return value;
    }
    value = await loader();
    at = Date.now();
    return value;
  };
}

async function walkProjectFiles(directory, into, depth = 0) {
  if (depth > 8) return into;

  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    return into;
  }

  for (const entry of entries) {
    if (entry.name.startsWith(".") && entry.isDirectory()) {
      if (SKIP_DIRECTORIES.has(entry.name)) continue;
    }
    if (SKIP_DIRECTORIES.has(entry.name)) continue;

    const full = join(directory, entry.name);
    if (entry.isDirectory()) {
      await walkProjectFiles(full, into, depth + 1);
    } else if (entry.isFile()) {
      into.push(relative(PROJECT_ROOT, full).split(sep).join("/"));
    }
  }

  return into;
}

const loadProjectFiles = cached(async () => {
  const files = await walkProjectFiles(PROJECT_ROOT, []);
  files.sort();
  return files.map((path) => ({ value: path, label: path }));
});

const loadPackages = cached(async () => {
  const modules = join(PROJECT_ROOT, "node_modules");
  let entries;
  try {
    entries = await readdir(modules, { withFileTypes: true });
  } catch {
    return [];
  }

  const names = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
    if (entry.name.startsWith("@")) {
      const scoped = await readdir(join(modules, entry.name), { withFileTypes: true })
        .catch(() => []);
      for (const inner of scoped) {
        if (inner.isDirectory()) names.push(`${entry.name}/${inner.name}`);
      }
    } else {
      names.push(entry.name);
    }
  }

  names.sort();
  return names.map((name) => ({ value: name, label: name }));
});

const loadSkills = cached(async () => {
  const skillsDir = join(PROJECT_ROOT, ".claude", "skills");
  let entries;
  try {
    entries = await readdir(skillsDir, { withFileTypes: true });
  } catch {
    return [];
  }

  const skills = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith(".")) continue;

    const skillFile = join(skillsDir, entry.name, "SKILL.md");
    try {
      const content = await readFile(skillFile, "utf8");
      const match = content.match(/^---\s*\nname:\s*(.+?)\s*\ndescription:\s*(.+?)\s*\n---/s);
      if (match) {
        skills.push({
          value: entry.name,
          label: match[1].trim(),
          description: match[2].trim(),
        });
      } else {
        skills.push({
          value: entry.name,
          label: entry.name,
          description: "",
        });
      }
    } catch {
      // 没有 SKILL.md 或解析失败，跳过
      continue;
    }
  }

  skills.sort((a, b) => a.label.localeCompare(b.label));
  return skills;
});

/**
 * 数据源注册表。search 只返回一页，resolve 负责把引用还原成模型可读的描述——
 * 服务端一律重新解析，绝不相信前端传来的标签。
 */
const SOURCES = {
  file: {
    label: "项目文件",
    hint: "按路径搜索项目中的文件",
    list: loadProjectFiles,
    async resolve(value) {
      const files = await loadProjectFiles();
      const file = files.find((item) => item.value === value);
      if (!file) return null;

      const path = resolve(PROJECT_ROOT, value);
      const root = resolve(PROJECT_ROOT);
      if (path !== root && !path.startsWith(`${root}${sep}`)) return null;

      const info = await stat(path).catch(() => null);
      if (!info?.isFile()) return null;

      return {
        label: file.label,
        detail: `路径：${path}；${info.size} 字节`,
      };
    },
  },
  skill: {
    label: "技能",
    hint: "按名称搜索可用的 Skill",
    list: loadSkills,
    async resolve(value) {
      const skills = await loadSkills();
      const skill = skills.find((item) => item.value === value);
      if (!skill) return null;

      return {
        label: skill.label,
        detail: skill.description || "无描述",
      };
    },
  },
  pkg: {
    label: "已安装依赖",
    hint: "按包名搜索 node_modules 里的依赖",
    list: loadPackages,
    async resolve(value) {
      const packages = await loadPackages();
      if (!packages.some((item) => item.value === value)) return null;

      const manifest = join(PROJECT_ROOT, "node_modules", value, "package.json");
      const raw = await readFile(manifest, "utf8").catch(() => null);
      if (!raw) return { label: value, detail: "" };

      try {
        const parsed = JSON.parse(raw);
        return {
          label: value,
          detail: [parsed.version && `v${parsed.version}`, parsed.description]
            .filter(Boolean)
            .join(" · "),
        };
      } catch {
        return { label: value, detail: "" };
      }
    },
  },
};

export function listSources() {
  return ["skill", "pkg", "file"]
    .filter((type) => Object.hasOwn(SOURCES, type))
    .map((type) => ({
      type,
      label: SOURCES[type].label,
      hint: SOURCES[type].hint,
    }));
}

export function isSource(type) {
  return Object.hasOwn(SOURCES, type);
}

/** 子串匹配 + 前缀优先。规模到十万级要换成数据库查询，接口形状不变。 */
export async function searchSource(type, query, { limit = DEFAULT_LIMIT, offset = 0 } = {}) {
  const source = SOURCES[type];
  if (!source) return null;

  const size = Math.min(Math.max(Number(limit) || DEFAULT_LIMIT, 1), MAX_LIMIT);
  const from = Math.max(Number(offset) || 0, 0);
  const needle = String(query || "").trim().toLowerCase();
  const all = await source.list();

  const matched = needle
    ? all.filter((item) => item.label.toLowerCase().includes(needle))
    : all;

  if (needle) {
    matched.sort((a, b) => {
      const rank =
        Number(b.label.toLowerCase().startsWith(needle)) -
        Number(a.label.toLowerCase().startsWith(needle));
      return rank || a.label.length - b.label.length || a.label.localeCompare(b.label);
    });
  }

  return {
    type,
    total: matched.length,
    offset: from,
    items: matched.slice(from, from + size).map((item) => ({
      value: item.value,
      label: item.label,
      reference: `@${type}:${encodeReferenceValue(item.value)}`,
    })),
  };
}

/**
 * 把 prompt 里的引用展开成一段上下文。模型据此知道每个标记指向什么，
 * 而 context 增量只和引用条数成正比，与候选集大小无关。
 */
export async function referencePromptContext(prompt) {
  const references = parseReferences(prompt);
  if (!references.length) return "";

  const lines = [];
  for (const reference of references) {
    const source = SOURCES[reference.type];
    if (!source) {
      lines.push(`- ${reference.raw}：未知引用类型，忽略。`);
      continue;
    }

    const resolved = await source.resolve(reference.value);
    if (!resolved) {
      lines.push(`- ${reference.raw}：在${source.label}中不存在，不要凭猜测使用。`);
      continue;
    }

    lines.push(
      `- ${reference.raw} → ${source.label}：${resolved.label}` +
        (resolved.detail ? `（${resolved.detail}）` : ""),
    );
  }

  return [
    "用户在提问中使用了引用标记，对应的真实对象如下（由服务端解析，可信）：",
    ...lines,
    "引用 @skill: 时遵循该 Skill 的工作流程和规则。",
  ].join("\n");
}
