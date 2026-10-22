import test from "node:test";
import assert from "node:assert/strict";
import { buildEdit, canEditPending, createDraft, draftAllocations, draftTotals, offeringLine, replaceLine, savePendingEdit, switchMode, validateDraft } from "../src/lib/pending-edit.ts";
import { ApiError } from "../src/lib/api.ts";

function order() {
  return { order_id: 1, version: 4, is_received: false, service_date: "2040-01-02", menu_id: 10,
    employee_number: "0001", visitor_id: null, customer_name: "Synthetic Employee", position: null, campaign: null, line_of_business: null,
    items: [
      { id: 101, line_number: 1, source_menu_item_id: 11, name: "Synthetic Vegetable", category: "vegetable", unit_price: "50.00", quantity: 1, line_total: "50.00" },
      { id: 102, line_number: 2, source_menu_item_id: 12, name: "Synthetic Meal", category: "non_vegetable", unit_price: "75.00", quantity: 2, line_total: "150.00" },
    ], allocations: [{ id: 201, category: "cash", amount: "200.00" }] };
}
const offering = { id: 13, dish_id: 3, item_name: "Synthetic Extra Rice", category_code: "extra_rice", unit_price: "15.00" };

test("Pending details prepopulate without changing the original snapshots or allocations", () => {
  const saved = order(), original = structuredClone(saved), draft = createDraft(saved);
  assert.equal(draft.lines[0].quantity, "1");
  assert.equal(draft.lines[0].unitPrice, "50.00");
  assert.equal(draft.single, "cash"); assert.equal(draft.split, false); assert.equal(draft.amounts.cash, "200.00");
  draft.lines[0].quantity = "3"; draft.amounts.cash = "100.00";
  const patch = buildEdit(saved, draft);
  assert.deepEqual(patch.quantities, [{ line_id: 101, quantity: 3 }]);
  assert.deepEqual(patch.add_items, []); assert.deepEqual(patch.remove_line_ids, []);
  assert.deepEqual(saved, original);
  assert.equal(patch.expected_version, 4);
  assert.deepEqual(Object.keys(patch).sort(), ["expected_version", "quantities", "remove_line_ids", "add_items", "allocations"].sort());
  assert.equal(draftTotals(draft, false).total, 30000n);
});

test("adding, explicit replacement and removal map to the existing atomic PATCH contract", () => {
  const saved = order();
  let draft = createDraft(saved);
  draft.lines.push(offeringLine(offering, "new-1", "3"));
  let patch = buildEdit(saved, draft);
  assert.deepEqual(patch.add_items, [{ menu_item_id: 13, quantity: 3 }]);
  draft = replaceLine(draft, "saved-101", { ...offering, id: 14, unit_price: "60.00" });
  draft.lines = draft.lines.filter(line => line.lineId !== 102);
  patch = buildEdit(saved, draft);
  assert.deepEqual(patch.remove_line_ids, [101, 102]);
  assert.deepEqual(patch.quantities, []);
  assert.deepEqual(patch.add_items, [{ menu_item_id: 14, quantity: 1 }, { menu_item_id: 13, quantity: 3 }]);
  assert.equal(draftTotals(draft, false).total, 10500n);
  assert.equal(JSON.stringify(patch).includes("unit_price"), false);
  assert.equal(JSON.stringify(patch).includes("category_snapshot"), false);
});

test("last-line removal and invalid quantities show field validation", () => {
  const saved = order(), draft = createDraft(saved);
  draft.lines = [];
  assert.match(validateDraft(saved, draft).items, /at least one/);
  assert.throws(() => buildEdit(saved, draft));
  for (const quantity of ["0", "-1", "1.5", "", "2147483648", "1e2"]) {
    const invalid = createDraft(saved); invalid.lines[0].quantity = quantity;
    assert.ok(validateDraft(saved, invalid)["quantity-saved-101"]);
    assert.equal(draftTotals(invalid, false).total, null);
  }
});

test("single and split changes preserve entered amounts and permit incomplete or empty Pending allocations", () => {
  const saved = order(); let draft = switchMode(createDraft(saved), true);
  draft.amounts = { cash: "150.00", gcash: "25.00", sd: "10.00" };
  assert.deepEqual(draftAllocations(draft, false), [{ category: "cash", amount: "150.00" }, { category: "gcash", amount: "25.00" }, { category: "sd", amount: "10.00" }]);
  assert.deepEqual(draftTotals(draft, false), { total: 20000n, allocated: 18500n, difference: 1500n });
  draft = switchMode(draft, false);
  assert.deepEqual(buildEdit(saved, draft).allocations, [{ category: "cash", amount: "150.00" }]);
  draft.amounts = {};
  assert.deepEqual(buildEdit(saved, draft).allocations, []);
  assert.equal(draftTotals(draft, false).difference, 20000n);
  for (const amount of ["0", "-1", "NaN", "1.001"]) {
    draft.amounts.cash = amount;
    assert.ok(validateDraft(saved, draft)["amount-cash"]);
    assert.throws(() => buildEdit(saved, draft));
  }
});

test("visitor Finance automatically follows item totals", () => {
  const saved = { ...order(), employee_number: null, visitor_id: 7, allocations: [{ id: 201, category: "finance", amount: "200.00" }] };
  const draft = createDraft(saved);
  assert.equal(draft.single, "finance"); draft.amounts.finance = "50.00";
  assert.deepEqual(buildEdit(saved, draft).allocations, [{ category: "finance", amount: "200.00" }]);
  draft.lines[0].quantity = "2";
  assert.deepEqual(buildEdit(saved, draft).allocations, [{ category: "finance", amount: "250.00" }]);
  draft.amounts.cash = "10.00";
  assert.match(validateDraft(saved, draft).allocations, /Finance only/);
  assert.throws(() => buildEdit(saved, draft));
});

test("Cancel discards a separate draft without modifying the saved record", () => {
  const saved = order(), original = structuredClone(saved);
  const cancelledDraft = createDraft(saved);
  cancelledDraft.lines.splice(0, 1); cancelledDraft.amounts.cash = "1.00";
  // Cancel simply discards this draft; creation and updates have no side effects.
  assert.deepEqual(saved, original);
  assert.equal(createDraft(saved).lines.length, 2);
  assert.equal(createDraft(saved).amounts.cash, "200.00");
});

test("Received editing is hidden for both roles and cannot be submitted from a stale Received detail", async () => {
  for (const role of ["admin", "assistant_admin"]) {
    assert.equal(canEditPending(role, false), true);
    assert.equal(canEditPending(role, true), false);
  }
  const saved = order(), received = { ...saved, is_received: true };
  assert.throws(() => createDraft(received), /Received/);
  let calls = 0;
  await assert.rejects(savePendingEdit(async () => { calls++; }, received, createDraft(saved)));
  assert.equal(calls, 0);
});

test("successful save PATCHes the expected version once and reads authoritative updated details", async () => {
  const saved = order(), draft = createDraft(saved), calls = [];
  draft.lines[0].quantity = "2";
  const updated = { ...saved, version: 5, items: [{ ...saved.items[0], quantity: 2, line_total: "100.00" }, saved.items[1]] };
  const result = await savePendingEdit(async (path, options) => {
    calls.push({ path, options });
    return options?.method === "PATCH" ? { order_id: 1, version: 5 } : updated;
  }, saved, draft);
  assert.equal(result, updated);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].options.method, "PATCH"); assert.equal(calls[0].options.body.expected_version, 4);
  assert.deepEqual(calls[0].options.body.quantities, [{ line_id: 101, quantity: 2 }]);
  assert.equal(calls[1].options, undefined);
});

test("stale, expired, forbidden, missing, and rejected saves never retry or adopt a new version", async () => {
  for (const status of [409, 401, 403, 404, 422]) {
    let calls = 0;
    const saved = order();
    await assert.rejects(savePendingEdit(async () => { calls++; throw new ApiError(status); }, saved, createDraft(saved)), error => error.status === status);
    assert.equal(calls, 1); assert.equal(saved.version, 4);
  }
});
