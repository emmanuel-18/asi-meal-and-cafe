import test from "node:test";
import assert from "node:assert/strict";
import { ApiError } from "../src/lib/api.ts";
import { addDate, alphabetical, assignMenu, createDish, createMenu, inspectDates, menuInput, needsReplacement, referencePrices, scheduleInput, searchDishes, selectDish } from "../src/lib/menus.ts";

const dish = { id: 1, name: "Synthetic Vegetable", category_code: "vegetable", is_active: true };

test("catalog search uses actual filters, bounded pages and alphabetical fallback", async () => {
  const calls = [];
  const result = await searchDishes(async path => {
    const query = new URL(path, "http://test.invalid").searchParams;
    calls.push(query);
    return query.get("offset") === "0" ? Array.from({ length: 100 }, (_, i) => ({ ...dish, id: i + 2, name: `Z synthetic ${i}` })) : [{ ...dish, name: "A synthetic" }];
  }, { q: " synthetic & rice ", category: "vegetable", active: "true" });
  assert.equal(calls.length, 2); assert.equal(calls[0].get("q"), "synthetic & rice");
  assert.equal(calls[0].get("category"), "vegetable"); assert.equal(calls[0].get("active"), "true");
  assert.equal(calls[0].get("limit"), "100"); assert.equal(calls[1].get("offset"), "100");
  assert.equal(result.dishes[0].name, "A synthetic"); assert.equal(result.truncated, false);
  assert.deepEqual(alphabetical([{ ...dish, id: 2 }, dish]).map(d => d.id), [1, 2]);
});

test("catalog search caps results and treats empty/error states honestly", async () => {
  let calls = 0;
  const full = await searchDishes(async () => { calls++; return Array.from({ length: 100 }, (_, i) => ({ ...dish, id: calls * 100 + i })); }, { q: "", category: "", active: "" });
  assert.equal(calls, 10); assert.equal(full.dishes.length, 1000); assert.equal(full.truncated, true);
  assert.deepEqual(await searchDishes(async () => [], { q: "none", category: "", active: "" }), { dishes: [], truncated: false });
  await assert.rejects(searchDishes(async () => { throw new ApiError(401); }, { q: "", category: "", active: "" }), error => error.status === 401);
});

test("create reusable dish sends only approved fields and can immediately select the returned identity", async () => {
  let call;
  const created = await createDish(async (path, options) => { call = { path, options }; return { ...dish, id: 5 }; }, " Synthetic Vegetable ", "vegetable");
  assert.deepEqual(call, { path: "/api/dishes", options: { method: "POST", body: { name: "Synthetic Vegetable", category_code: "vegetable" } } });
  assert.deepEqual(selectDish([], created), [created]);
  await assert.rejects(createDish(async () => assert.fail("invalid name must not be submitted"), "  ", "vegetable"));
});

test("selection prevents duplicate IDs and inactive selection without merging names", () => {
  const selected = selectDish([], dish);
  assert.equal(selectDish(selected, dish), selected);
  assert.equal(selectDish(selected, { ...dish, id: 2 }).length, 2);
  assert.throws(() => selectDish([], { ...dish, is_active: false }), /Inactive/);
  assert.throws(() => selectDish(Array.from({ length: 100 }, (_, i) => ({ ...dish, id: i + 10 })), dish), /100/);
});

test("new menu review builds only a label and distinct dish IDs; prices remain server-owned", async () => {
  assert.deepEqual(menuInput("  ", [dish]), { label: null, dish_ids: [1] });
  assert.throws(() => menuInput("label", [dish, dish]), /distinct/);
  assert.throws(() => menuInput("label", []));
  assert.throws(() => menuInput("label", [{ ...dish, is_active: false }]));
  const saved = { id: 8, label: "Synthetic", items: [{ id: 9, dish_id: 1, item_name: dish.name, category_code: "vegetable", unit_price: "60.00" }] };
  let body;
  const result = await createMenu(async (path, options) => { assert.equal(path, "/api/menus"); assert.equal(options.method, "POST"); body = options.body; return saved; }, " Synthetic ", [dish]);
  assert.deepEqual(body, { label: "Synthetic", dish_ids: [1] });
  assert.equal(result.items[0].unit_price, "60.00");
  assert.equal(referencePrices.vegetable, "50.00"); // Clearly separate approved reference from actual saved price.
  assert.equal("unit_price" in body, false); assert.equal("actor_id" in body, false);
});

test("multiple service dates are explicit, sorted, unique and valid across weeks/months", () => {
  let dates = addDate([], "2040-03-01"); dates = addDate(dates, "2040-02-04"); dates = addDate(dates, "2040-02-06");
  assert.deepEqual(dates, ["2040-02-04", "2040-02-06", "2040-03-01"]);
  assert.equal(addDate(dates, "2040-03-01"), dates);
  for (const invalid of ["2040-02-30", "2040-13-01", "0000-01-01", "", "2040-02-01T00:00:00Z"]) assert.throws(() => addDate([], invalid));
});

test("date inspection records existing assignments and only a 404 means unassigned", async () => {
  const calls = [];
  const reviewed = await inspectDates(async path => {
    calls.push(path); if (path.endsWith("2040-02-06")) throw new ApiError(404);
    return { id: 8, label: "Synthetic existing", service_date: "2040-02-04", items: [] };
  }, ["2040-02-06", "2040-02-04"]);
  assert.deepEqual(calls, ["/api/menus/by-date/2040-02-04", "/api/menus/by-date/2040-02-06"]);
  assert.deepEqual(reviewed, [{ service_date: "2040-02-04", expected_menu_id: 8, label: "Synthetic existing" }, { service_date: "2040-02-06", expected_menu_id: null, label: null }]);
  for (const status of [401, 403, 503]) await assert.rejects(inspectDates(async () => { throw new ApiError(status); }, ["2040-02-04"]), error => error.status === status);
});

test("each replacement requires confirmation and scheduling keeps reviewed expected IDs", async () => {
  const rows = [ { service_date: "2040-02-04", expected_menu_id: 8, label: "Old" }, { service_date: "2040-02-06", expected_menu_id: null, label: null } ];
  assert.equal(needsReplacement(rows[0], 9), true); assert.equal(needsReplacement(rows[0], 8), false);
  assert.throws(() => scheduleInput(9, rows, []), /Confirm each/);
  assert.throws(() => scheduleInput(9, rows, ["2040-02-06"]), /Confirm each/);
  let call;
  await assignMenu(async (path, options) => { call = { path, options }; return { menu_id: 9, service_dates: rows.map(r => r.service_date) }; }, 9, rows, ["2040-02-04"]);
  assert.deepEqual(call, { path: "/api/menus/9/dates", options: { method: "PUT", body: { assignments: [
    { service_date: "2040-02-04", expected_menu_id: 8 }, { service_date: "2040-02-06", expected_menu_id: null }] } } });
  assert.deepEqual(scheduleInput(8, [rows[0]], []).assignments, [{ service_date: "2040-02-04", expected_menu_id: 8 }]);
});

test("stale and expired scheduling is never retried and no historical order fields are submitted", async () => {
  const row = { service_date: "2040-02-04", expected_menu_id: 8, label: "Existing" };
  const historical = Object.freeze({ order_id: 5, menu_id: 8, unit_price: "50.00", version: 2 });
  for (const status of [409, 401, 403, 422, 503]) {
    let calls = 0;
    await assert.rejects(assignMenu(async () => { calls++; throw new ApiError(status); }, 9, [row], [row.service_date]), error => error.status === status);
    assert.equal(calls, 1); assert.equal(row.expected_menu_id, 8);
  }
  assert.deepEqual(historical, { order_id: 5, menu_id: 8, unit_price: "50.00", version: 2 });
});
