import test from "node:test";
import assert from "node:assert/strict";
import { ApiError } from "../src/lib/api.ts";
import { dailyMenu, defaultRicePrice, editableMenuDishes, saveDailyMenu } from "../src/lib/daily-menu.ts";
import { createMenu, assignMenu } from "../src/lib/menus.ts";

test("editing a saved menu excludes deleted dishes but retains active dishes", () => {
  const menu = { items: [{ dish_id: 1, category_code: "vegetable" }, { dish_id: 2, category_code: "non_vegetable" }, { dish_id: 3, category_code: "extra_rice" }] };
  const catalog = [{ id: 1, name: "Synthetic vegetable", is_active: false }, { id: 2, name: "Synthetic meal", is_active: true }];
  assert.deepEqual(editableMenuDishes(menu, catalog), [catalog[1]]);
  assert.throws(() => editableMenuDishes(menu, []), /not found/);
});

test("save submits selection and staged dish changes together for the selected date", async () => {
  const original = { id: 1, name: "Synthetic", category_code: "vegetable", is_active: true };
  let sent;
  await saveDailyMenu(async (path, options) => { assert.equal(path, "/api/menus"); sent = options.body; return {}; }, "2040-01-02", 9, [{ ...original, id: 2 }], [{ original, updated: null }]);
  assert.deepEqual(sent.assignments, [{ service_date: "2040-01-02", expected_menu_id: 9 }]);
  assert.deepEqual(sent.dish_changes, [{ id: 1, expected_name: "Synthetic", expected_category: "vegetable", delete: true }]);
  assert.deepEqual(sent.dish_ids, [2]);
});

test("date lookup distinguishes unassigned from failures and preserves authoritative prices", async () => {
  const menu = { id: 3, service_date: "2040-01-02", items: [{ dish_id: 7, category_code: "extra_rice", unit_price: "27.50" }] };
  assert.equal(await dailyMenu(async path => { assert.equal(path, "/api/menus/by-date/2040-01-02"); return menu; }, "2040-01-02"), menu);
  assert.equal((await dailyMenu(async () => menu, "2040-01-02")).items[0].unit_price, "27.50");
  assert.equal(await dailyMenu(async () => { throw new ApiError(404); }, "2040-01-02"), null);
  await assert.rejects(dailyMenu(async () => { throw new ApiError(503); }, "2040-01-02"));
});

test("default rice price comes from the server and failures are surfaced", async () => {
  assert.equal(await defaultRicePrice(async path => { assert.equal(path, "/api/menu-defaults"); return { extra_rice_price: "27.50" }; }), "27.50");
  await assert.rejects(defaultRicePrice(async () => { throw new ApiError(503); }));
});

test("menu definition precedes explicit assignment with the reviewed prior ID", async () => {
  const dish = { id: 7, name: "Synthetic Vegetable", category_code: "vegetable", is_active: true };
  const calls = [];
  const request = async (path, options) => { calls.push({ path, options }); return calls.length === 1 ? { id: 9, items: [] } : { menu_id: 9 }; };
  const menu = await createMenu(request, "", [dish], true);
  await assert.rejects(assignMenu(request, menu.id, [{ service_date: "2040-01-02", expected_menu_id: 4, label: null }], []));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.body.include_default_rice, true);
  await assignMenu(request, menu.id, [{ service_date: "2040-01-02", expected_menu_id: 4, label: null }], ["2040-01-02"]);
  assert.deepEqual(calls[1].options.body, { assignments: [{ service_date: "2040-01-02", expected_menu_id: 4 }] });
});
