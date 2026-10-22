import test from "node:test";
import assert from "node:assert/strict";
import { scheduleCustomerSearch, suggestionKey } from "../src/lib/customer-search.ts";

test("keyboard navigation selects only an active option and Tab or Escape dismisses", () => {
  assert.deepEqual(suggestionKey("ArrowDown", -1, 3, false), { action: "move", index: 0 });
  assert.deepEqual(suggestionKey("ArrowUp", -1, 3, false), { action: "move", index: 2 });
  assert.deepEqual(suggestionKey("ArrowDown", 2, 3, true), { action: "move", index: 2 });
  assert.deepEqual(suggestionKey("Enter", 1, 3, true), { action: "select", index: 1 });
  assert.equal(suggestionKey("Enter", -1, 3, true).action, "none");
  assert.equal(suggestionKey("Enter", 1, 3, false).action, "none");
  assert.equal(suggestionKey("Tab", 1, 3, true).action, "close");
  assert.equal(suggestionKey("Escape", 1, 3, true).action, "close");
});

test("search is debounced, bounded and preserves leading-zero employee identifiers", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0, found, done = 0;
  const cancel = scheduleCustomerSearch("employee", "  0001 ", async (path, options) => {
    calls++; assert.equal(path, "/api/employees?q=0001&limit=20"); assert.equal(options.signal.aborted, false);
    return Array.from({ length: 22 }, (_, i) => ({ employee_number: i ? String(i) : "0001", full_name: "Synthetic Person" }));
  }, rows => { found = rows; }, () => assert.fail("unexpected error"), () => done++);
  t.mock.timers.tick(274); assert.equal(calls, 0);
  t.mock.timers.tick(1); await Promise.resolve();
  assert.equal(calls, 1); assert.equal(found.length, 20); assert.deepEqual(found[0].customer, { employee_number: "0001", name: "Synthetic Person" });
  assert.equal(done, 1); cancel();
});

test("empty and cancelled searches never publish results, including late responses", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0, resolve, published = 0, signal;
  scheduleCustomerSearch("visitor", "   ", async () => { calls++; return []; }, () => published++, () => published++, () => published++);
  const cancel = scheduleCustomerSearch("visitor", "Synthetic", (path, options) => {
    calls++; signal = options.signal; assert.equal(path, "/api/visitors?q=Synthetic&limit=20");
    return new Promise(done => { resolve = done; });
  }, () => published++, () => published++, () => published++);
  t.mock.timers.tick(275); assert.equal(calls, 1); cancel(); assert.equal(signal.aborted, true);
  resolve([{ id: 7, display_name: "Synthetic Visitor" }]); await Promise.resolve();
  assert.equal(published, 0);
});

test("visitor results retain stable IDs and errors reach the retry state", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let rows, error, done = 0;
  scheduleCustomerSearch("visitor", "Sam", async () => [{ id: 7, display_name: "Synthetic Visitor" }], value => { rows = value; }, () => assert.fail(), () => done++);
  t.mock.timers.tick(275); await Promise.resolve();
  assert.deepEqual(rows[0], { customer: { visitor_id: 7, name: "Synthetic Visitor" }, detail: "Visitor #7" });
  scheduleCustomerSearch("visitor", "Sam", async () => { throw new Error("Synthetic failure"); }, () => assert.fail(), value => { error = value; }, () => done++);
  t.mock.timers.tick(275); await Promise.resolve();
  assert.equal(error.message, "Synthetic failure"); assert.equal(done, 2);
});
