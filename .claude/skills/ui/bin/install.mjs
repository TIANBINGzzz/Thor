#!/usr/bin/env node
import { mkdirSync, copyFileSync, readdirSync, statSync, rmSync, existsSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { homedir } from "os";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = join(__dirname, "..");

const TARGET = join(homedir(), ".claude", "skills", "ui");

const FILES_TO_COPY = ["SKILL.md", "tokens.md", "anti-slop.md", "review.md", "architecture.md", "redesign.md", "image-generation.md", "visual-thinking.md"];
const DIRS_TO_COPY = ["recipes", "assets"];

function copyDir(src, dest) {
  mkdirSync(dest, { recursive: true });
  for (const entry of readdirSync(src)) {
    const s = join(src, entry);
    const d = join(dest, entry);
    if (statSync(s).isDirectory()) {
      copyDir(s, d);
    } else {
      copyFileSync(s, d);
    }
  }
}

function countFiles(dir) {
  let n = 0;
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      n += countFiles(p);
    } else {
      n += 1;
    }
  }
  return n;
}

const isDryRun = process.argv.includes("--dry-run");

console.log("");
console.log("  ╔═══════════════════════════════════════════╗");
console.log("  ║   /ui skill installer                     ║");
console.log("  ║   Premium UI for Claude Code              ║");
console.log("  ║   v2.3.0 — 17 photoreal device mockups       ║");
console.log("  ╚═══════════════════════════════════════════╝");
console.log("");

if (isDryRun) {
  console.log("  [DRY RUN] Would install to:", TARGET);
  console.log("");
  process.exit(0);
}

if (existsSync(TARGET)) {
  // Backup OUTSIDE the skills folder so Claude doesn't load it as a duplicate skill
  const backupRoot = join(homedir(), ".claude", "backups");
  mkdirSync(backupRoot, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const backup = join(backupRoot, `ui-skill-backup-${ts}`);
  console.log("  ⚠  Existing skill found, backing up to:", backup);
  copyDir(TARGET, backup);
  rmSync(TARGET, { recursive: true, force: true });
  console.log("  ✓  Backed up");
}

mkdirSync(TARGET, { recursive: true });

for (const f of FILES_TO_COPY) {
  copyFileSync(join(PACKAGE_ROOT, f), join(TARGET, f));
}

for (const d of DIRS_TO_COPY) {
  copyDir(join(PACKAGE_ROOT, d), join(TARGET, d));
}

const fileCount = countFiles(TARGET);

console.log("");
console.log("  ✓  Installed to", TARGET);
console.log("  ✓ ", fileCount, "files");
console.log("");
console.log("  What's included (v2.1.0):");
console.log("    • SKILL.md — 3 rules + 7-step procedure (RESTRAINT/MOTION dials, motion-mandatory floor)");
console.log("    • tokens.md — 4 palettes (warm/cool/dark/stone) + premium button shadows + Liquid Glass");
console.log("    • anti-slop.md — patterns that scream 'AI-generated' (incl. Jane Doe content rules)");
console.log("    • review.md — 16-item pre-ship Playwright checklist");
console.log("    • architecture.md — RSC client/server boundaries (Next.js App Router)");
console.log("    • redesign.md — companion procedure for upgrading existing UIs");
console.log("    • image-generation.md — optional AI image-gen integration guide");
console.log("    • recipes/ — 28 ready-to-adapt React components");
console.log("    • recipes/animations.md — 41 CSS animation patterns (transitions.dev style)");
console.log("    • recipes/mockups.md — device frames (BrowserFrame/iPhoneFrame/MacBookFrame/etc) + 9 content primitives");
console.log("    • assets/backgrounds/ — 26 bundled WebP backgrounds");
console.log("");
console.log("  Usage in Claude Code:");
console.log("    /ui              # invoke the skill");
console.log("    /ui build me a fintech landing page for [product]");
console.log("");
console.log("  Source: github.com/theylovlj/ui-skill");
console.log("");
