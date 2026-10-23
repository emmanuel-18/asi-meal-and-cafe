import test from "node:test";
import assert from "node:assert/strict";
import { allocationTotal, buildOrder, canConfirm, canReverse, centavos, decimal, itemTotal, pesos, reasons } from "../src/lib/meal.ts";

const menu = { id: 10, service_date: "2040-01-02", label: "Synthetic Menu", items: [
  { id: 1, dish_id: 1, item_name: "Synthetic Vegetable", category_code: "vegetable", unit_price: "50.00" },
  { id: 2, dish_id: 2, item_name: "Synthetic Meal", category_code: "non_vegetable", unit_price: "75.00" },
  { id: 3, dish_id: 3, item_name: "Synthetic Rice", category_code: "extra_rice", unit_price: "15.00" },
] };

test("quantities and split difference use exact centavos from supplied menu prices", () => {
  const total = itemTotal(menu, { 1: 1, 2: 2, 3: 3 });
  assert.equal(total, 24500n);
  assert.equal(allocationTotal([{ category: "gcash", amount: "200.00" }, { category: "cash", amount: "45.00" }]), total);
  assert.equal(total - allocationTotal([{ category: "sd", amount: "200" }]), 4500n);
  assert.equal(itemTotal({ ...menu, items: [{ ...menu.items[0], unit_price: "60.00" }] }, { 1: 2 }), 12000n);
  assert.equal(centavos("0.10") + centavos("0.20"), 30n);
  assert.equal(decimal(-30n), "-0.30");
  assert.equal(pesos(123456n), "₱1,234.56");
  assert.equal(pesos("10000000000.00"), "₱10,000,000,000.00");
  for (const invalid of ["NaN", "-1", "1.001", "1e3", "10000000000", "", " 5 "]) assert.equal(centavos(invalid), null);
  for (const invalid of [0, -1, 1.2, Infinity]) {
    if (invalid === 0) assert.equal(itemTotal(menu, { 1: invalid }), 0n);
    else assert.throws(() => itemTotal(menu, { 1: invalid }));
  }
});

test("order payload preserves text identifiers and includes only approved inputs", () => {
  const payload = buildOrder("synthetic-key", menu, { 1: 2 }, { employee_number: "0001" }, [{ category: "sd", amount: "100.00" }]);
  assert.deepEqual(payload, { request_key: "synthetic-key", service_date: "2040-01-02", menu_id: 10,
    employee_number: "0001", items: [{ menu_item_id: 1, quantity: 2 }], allocations: [{ category: "sd", amount: "100.00" }] });
  assert.equal("unit_price" in payload.items[0], false);
  assert.equal("actor_id" in payload, false);
  assert.throws(() => buildOrder("key", menu, { 1: 1 }, { visitor_id: 2 }, [{ category: "cash", amount: "50" }]));
  assert.equal(buildOrder("key", menu, { 1: 1 }, { visitor_id: 2 }, [{ category: "finance", amount: "50" }]).visitor_id, 2);
  assert.throws(() => buildOrder("key", menu, {}, { employee_number: "0001" }, []));
  assert.equal(allocationTotal([{ category: "cash", amount: "0" }]), null);
});

test("reversal controls require Admin, current Received, acknowledgement and Other explanation", () => {
  assert.equal(canReverse("admin", true), true);
  assert.equal(canReverse("super_admin", true), true);
  assert.equal(canReverse("assistant_admin", true), false);
  assert.equal(canReverse("admin", false), false);
  assert.equal(canConfirm("other", "   ", true), false);
  assert.equal(canConfirm("other", "Synthetic correction", false), false);
  assert.equal(canConfirm("other", "Synthetic correction", true), true);
  assert.equal(canConfirm("mistaken_click", "", true), true);
  assert.deepEqual(reasons.map(r => r[1]), ["Mistaken click", "Incorrect employee marked", "Incorrect order marked", "Incorrect order details", "Other reason"]);
});
