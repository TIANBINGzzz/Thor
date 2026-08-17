import { strict as assert } from "node:assert";
import { test } from "node:test";
import { listSources, searchSource } from "./references.mjs";

test("listSources includes skill type", () => {
  const sources = listSources();
  const skillSource = sources.find((s) => s.type === "skill");
  assert.ok(skillSource, "skill source should exist");
  assert.equal(skillSource.label, "技能");
});

test("searchSource finds existing skills", async () => {
  const result = await searchSource("skill", "", { limit: 10 });
  assert.ok(result, "should return result");
  assert.equal(result.type, "skill");
  assert.ok(Array.isArray(result.items), "items should be array");
});

test("skill references are properly formatted", async () => {
  const result = await searchSource("skill", "", { limit: 1 });
  if (result.items.length > 0) {
    const item = result.items[0];
    assert.ok(item.reference.startsWith("@skill:"), "reference should start with @skill:");
    assert.ok(item.label, "should have label");
    assert.ok(item.value, "should have value");
  }
});
