import assert from "node:assert/strict";
import { test } from "node:test";

import {
  decodeReferenceValue,
  encodeReferenceValue,
  isSource,
  listSources,
  parseReferences,
  referencePromptContext,
  searchSource,
} from "./references.mjs";

test("解析出引用的类型和值", () => {
  const found = parseReferences("请读 @file:app/server.mjs 然后总结");
  assert.deepEqual(found, [
    { type: "file", value: "app/server.mjs", raw: "@file:app/server.mjs" },
  ]);
});

test("同一个引用重复出现只算一次", () => {
  const found = parseReferences("@pkg:marked 和 @pkg:marked");
  assert.equal(found.length, 1);
});

test("中文标点终止引用，不会被吞进 value", () => {
  assert.equal(parseReferences("看 @file:readme.md，然后呢")[0].value, "readme.md");
  assert.equal(parseReferences("看 @file:readme.md。")[0].value, "readme.md");
  assert.equal(parseReferences("看 @file:readme.md、和别的")[0].value, "readme.md");
  assert.equal(parseReferences("看 @file:readme.md 然后呢")[0].value, "readme.md");
});

test("路径里的点和斜杠仍然保留", () => {
  const found = parseReferences("读 @file:app/public/app.js");
  assert.equal(found[0].value, "app/public/app.js");
});

test("作用域包名里的 @ 和斜杠能通过引用往返", () => {
  const value = "@anthropic-ai/claude-agent-sdk";
  const found = parseReferences(`看 @pkg:${encodeReferenceValue(value)}`);
  assert.equal(found.length, 1);
  assert.equal(found[0].value, value);
});


test("带空白的路径能被解析回原值", () => {
  const encoded = encodeReferenceValue("a b/c.md");
  const found = parseReferences(`读 @file:${encoded} 谢谢`);
  assert.equal(found[0].value, "a b/c.md");
});

test("非引用的邮箱和普通 @ 不会误匹配", () => {
  assert.deepEqual(parseReferences("联系 someone@example.com"), []);
  assert.deepEqual(parseReferences("@ 开头但没有类型"), []);
});

test("数据源注册表暴露已知类型", () => {
  const types = listSources().map((item) => item.type);
  assert.ok(types.includes("file"));
  assert.ok(types.includes("pkg"));
  assert.ok(isSource("file"));
  assert.ok(!isSource("nope"));
});

test("搜索只返回一页，并带总数", async () => {
  const page = await searchSource("file", "", { limit: 3 });
  assert.equal(page.items.length, 3);
  assert.ok(page.total > 3);
  assert.equal(page.offset, 0);
});

test("搜索命中项自带可插入的引用文本", async () => {
  const page = await searchSource("file", "server.mjs", { limit: 5 });
  const hit = page.items.find((item) => item.value === "app/server.mjs");
  assert.ok(hit);
  assert.equal(hit.reference, "@file:app/server.mjs");
});

test("前缀命中排在子串命中之前", async () => {
  const page = await searchSource("pkg", "marked", { limit: 10 });
  assert.equal(page.items[0].value, "marked");
});

test("offset 能翻页且不重复", async () => {
  const first = await searchSource("file", "", { limit: 2, offset: 0 });
  const second = await searchSource("file", "", { limit: 2, offset: 2 });
  const overlap = first.items.filter((item) =>
    second.items.some((other) => other.value === item.value),
  );
  assert.equal(overlap.length, 0);
});

test("未知数据源返回 null", async () => {
  assert.equal(await searchSource("nope", ""), null);
});

test("limit 被夹到上限，防止一次拉走整张表", async () => {
  const page = await searchSource("file", "", { limit: 9999 });
  assert.ok(page.items.length <= 50);
});

test("没有引用时不产生上下文", async () => {
  assert.equal(await referencePromptContext("普通问题"), "");
});

test("真实引用展开成可信描述", async () => {
  const context = await referencePromptContext("读 @file:package.json");
  assert.match(context, /@file:package\.json/);
  assert.match(context, /项目文件/);
  assert.match(context, /字节/);
});

test("伪造的引用被明确标为不存在", async () => {
  const context = await referencePromptContext("读 @file:app/not-real.mjs");
  assert.match(context, /不存在/);
});

test("未知类型的引用不会伪装成有效对象", async () => {
  const context = await referencePromptContext("看 @secret:token");
  assert.match(context, /未知引用类型/);
});
