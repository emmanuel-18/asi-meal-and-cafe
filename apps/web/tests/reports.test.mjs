import test from "node:test";
import assert from "node:assert/strict";
import { apiRequest, ApiError } from "../src/lib/api.ts";
import { paymentLabels, pesos } from "../src/lib/meal.ts";
import { categoryLabels } from "../src/lib/menus.ts";
import { initialFilter, loadReport, manilaDate, matchingEmployees, reportPath } from "../src/lib/reports.ts";

const filter = initialFilter(new Date("2040-02-28T16:30:00Z"));
const bundle = { sales: { period: { start: "2040-02-29", end: "2040-02-29" }, recognized_sales: "175.00", received_order_count: 1, item_quantity: 2, meal_quantity: 1,
  categories: [{ category: "vegetable", quantity: 1, amount: "50.00" }, { category: "non_vegetable", quantity: 0, amount: "0.00" }, { category: "extra_rice", quantity: 1, amount: "125.00" }], items: [] },
  payments: { period: { start: "2040-02-29", end: "2040-02-29" }, totals: [{ category: "cash", amount: "75.00" }, { category: "sd", amount: "100.00" }], total: "175.00" },
  salary_deduction: { period: { start: "2040-02-29", end: "2040-02-29" }, total: "100.00", employees: [{ employee_number: "0001", order_count: 2, sd_amount: "100.00" }],
    orders: [{ order_id: 1, employee_number: "0001", customer_name: "Synthetic Person", position: "Synthetic role", campaign: null, line_of_business: null, sd_amount: "40.00" },
      { order_id: 2, employee_number: "0001", customer_name: "Synthetic Former Name", position: null, campaign: null, line_of_business: null, sd_amount: "60.00" }] } };

test("Philippine date defaults use Manila even across UTC midnight", () => {
  assert.equal(manilaDate(new Date("2040-02-28T15:59:59Z")), "2040-02-28");
  assert.equal(manilaDate(new Date("2040-02-28T16:00:00Z")), "2040-02-29");
  assert.equal(filter.day, "2040-02-29");
});

test("date modes send only the backend's required fields and validate boundaries", () => {
  assert.equal(reportPath(filter), "/api/reports/bundle?mode=daily&day=2040-02-29");
  assert.equal(reportPath({ ...filter, mode: "weekly", day: "2040-03-01" }), "/api/reports/bundle?mode=weekly&day=2040-03-01");
  assert.equal(reportPath({ ...filter, mode: "monthly", month: "2040-02" }), "/api/reports/bundle?mode=monthly&year=2040&month=2");
  assert.equal(reportPath({ ...filter, mode: "custom", start: "2039-12-31", end: "2040-01-01" }), "/api/reports/bundle?mode=custom&start=2039-12-31&end=2040-01-01");
  for (const bad of [{ ...filter, day: "2041-02-29" }, { ...filter, month: "2040-13", mode: "monthly" }, { ...filter, mode: "custom", start: "2040-03-01", end: "2040-02-29" }]) assert.throws(() => reportPath(bad));
});

test("backend figures and split allocations are displayed without summing or numeric conversion", async () => {
  const calls = [];
  const request = async path => { calls.push(path); return bundle; };
  const data = await loadReport(request, filter);
  assert.equal(pesos(data.sales.recognized_sales), "₱175.00");
  assert.equal(pesos(data.payments.totals[0].amount), "₱75.00");
  assert.equal(pesos(data.payments.totals[1].amount), "₱100.00");
  assert.equal(pesos("99999999999999999999.01"), "₱99,999,999,999,999,999,999.01");
  assert.equal(categoryLabels.vegetable, "Vegetable"); assert.equal(paymentLabels.sd, "Salary Deduction");
  assert.equal(data.salary_deduction.employees[0].order_count, 2);
  assert.equal(matchingEmployees(data, "0001")[0].employee_number, "0001");
  assert.equal(matchingEmployees(data, "former name").length, 1);
  assert.equal(matchingEmployees(data, "missing").length, 0);
  assert.equal(matchingEmployees({ ...data, salary_deduction: { ...data.salary_deduction, employees: [], orders: [] } }, "").length, 0);
  await loadReport(request, filter); assert.equal(calls.length, 2);
});

test("authenticated read handles expired sessions and forbidden errors without exposing details", async t => {
  for (const status of [401, 403, 503]) {
    t.mock.method(globalThis, "fetch", async (_path, options) => {
      assert.equal(options.credentials, "same-origin"); assert.equal(options.cache, "no-store");
      return new Response("synthetic-private", { status });
    });
    await assert.rejects(loadReport(apiRequest, filter), error => error instanceof ApiError && error.status === status && !error.message.includes("synthetic-private"));
    t.mock.restoreAll();
  }
});
