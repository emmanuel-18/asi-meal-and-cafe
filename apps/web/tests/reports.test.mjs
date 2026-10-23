import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { apiRequest, ApiError } from "../src/lib/api.ts";
import { paymentLabels, pesos } from "../src/lib/meal.ts";
import { categoryLabels } from "../src/lib/menus.ts";
import { barWidth, initialFilter, loadReport, manilaDate, matchingEmployees, periodLabel, reportPath, salaryByCampaign } from "../src/lib/reports.ts";
import { downloadReport, excelMoney, paymentBarWidth, reportSections } from "../src/lib/report-export.ts";

test("PDF payment bar widths use centavo proportions and handle zero", () => {
  assert.equal(paymentBarWidth(0n, 10000n), 0);
  assert.equal(paymentBarWidth(null, 10000n), 0);
  assert.equal(paymentBarWidth(5000n, 10000n), 52.5);
  assert.equal(paymentBarWidth(10000n, 10000n), 105);
});

const filter = initialFilter(new Date("2040-02-28T16:30:00Z"));

test("campaign breakdown adds recorded allocations in exact centavos", () => {
  const orders = [{ campaign: "Synthetic A", sd_amount: "10.01" }, { campaign: "Synthetic A", sd_amount: "0.09" }, { campaign: null, sd_amount: "3.00" }];
  assert.deepEqual(salaryByCampaign(orders), [{ name: "Synthetic A", amount: 1010n }, { name: "Not recorded", amount: 300n }]);
  assert.equal(salaryByCampaign([{ campaign: "A", sd_amount: "invalid" }]), null);
  assert.equal(barWidth(300n, 1000n), "30%");
  assert.equal(barWidth(0n, 0n), "0%");
});
const bundle = { sales: { period: { start: "2040-02-29", end: "2040-02-29" }, recognized_sales: "175.00", received_order_count: 1, item_quantity: 2, meal_quantity: 1,
  categories: [{ category: "vegetable", quantity: 1, amount: "50.00" }, { category: "non_vegetable", quantity: 0, amount: "0.00" }, { category: "extra_rice", quantity: 1, amount: "125.00" }], items: [] },
  payments: { period: { start: "2040-02-29", end: "2040-02-29" }, totals: [{ category: "cash", amount: "75.00" }, { category: "sd", amount: "100.00" }], total: "175.00" },
  salary_deduction: { period: { start: "2040-02-29", end: "2040-02-29" }, total: "100.00", employees: [{ employee_number: "0001", order_count: 2, sd_amount: "100.00" }],
    orders: [{ order_id: 1, service_date: "2040-02-29", employee_number: "0001", customer_name: "Synthetic Person", position: "Synthetic role", campaign: null, line_of_business: null, sd_amount: "40.00" },
      { order_id: 2, service_date: "2040-02-29", employee_number: "0001", customer_name: "Synthetic Former Name", position: null, campaign: null, line_of_business: null, sd_amount: "60.00" }] } };

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


test("report heading names the exact server-returned weekly and monthly boundaries", () => {
  const weekly = periodLabel("weekly", { start: "2026-10-19", end: "2026-10-25" });
  assert.match(weekly, /Monday.Sunday/);
  assert.match(weekly, /Mon/); assert.match(weekly, /19/);
  assert.match(weekly, /Sun/); assert.match(weekly, /25/);
  assert.match(periodLabel("monthly", { start: "2026-10-01", end: "2026-10-31" }), /Monthly:.*1.*31/);
  assert.match(periodLabel("daily", { start: "2026-10-22", end: "2026-10-22" }), /Daily:.*Thu/);
});

test("download sections retain exact amounts and employee order snapshots", () => {
  const sections = reportSections(bundle);
  assert.equal(sections.find(section => section.title === "Sales summary").rows[0][1], "₱175.00");
  assert.equal(sections.find(section => section.title === "Payment allocations").rows.at(-1)[1], "₱175.00");
  const orders = sections.find(section => section.title === "Salary Deduction orders").rows;
  assert.equal(orders.length, 2);
  assert.equal(orders[1][2], "0001");
  assert.equal(orders[1][3], "Synthetic Former Name");
  assert.equal(orders[1][7], "₱60.00");
});

test("Excel download creates an actual workbook with the selected report", async () => {
  const previousDocument = globalThis.document;
  const previousCreate = URL.createObjectURL; const previousRevoke = URL.revokeObjectURL;
  let blob; let filename; let clicked = false;
  globalThis.document = { createElement: () => ({ set href(value) {}, set download(value) { filename = value; }, click() { clicked = true; } }) };
  URL.createObjectURL = value => { blob = value; return "blob:synthetic"; };
  URL.revokeObjectURL = () => {};
  try {
    await downloadReport(bundle, "daily", "excel");
    assert.ok(clicked); assert.match(filename, /2040-02-29.*\.xlsx$/);
    const ExcelJS = (await import("exceljs")).default;
    const workbook = new ExcelJS.Workbook(); await workbook.xlsx.load(await blob.arrayBuffer());
    assert.deepEqual(workbook.worksheets.map(sheet => sheet.name), ["Executive Overview", "Detailed Report", "SD Register"]);
    const text = workbook.getWorksheet("Detailed Report").getColumn(1).values.join(" ");
    assert.match(text, /Sales summary/); assert.match(workbook.getWorksheet("SD Register").getColumn(1).values.join(" "), /Salary Deduction orders/);
    const sheet = workbook.getWorksheet("Detailed Report");
    let sales; sheet.eachRow(row => { if (row.getCell(1).value === "Recognized sales") sales = row.getCell(2); });
    assert.equal(sales.value, 175); assert.equal(sales.numFmt, '"₱"#,##0.00');
  } finally { globalThis.document = previousDocument; URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke; }
});

test("numeric Excel amounts retain cents and large amounts fall back to text", () => {
  assert.equal(excelMoney("₱0.01"), 0.01);
  assert.equal(excelMoney("₱1,234.56"), 1234.56);
  assert.equal(excelMoney("₱99,999,999,999,999,999,999.01"), null);
});

test("Excel stores untrusted formula-like values as text and wraps long names", async () => {
  const previousDocument = globalThis.document, previousCreate = URL.createObjectURL, previousRevoke = URL.revokeObjectURL;
  let blob;
  globalThis.document = { createElement: () => ({ click() {} }) };
  URL.createObjectURL = value => { blob = value; return "blob:synthetic"; }; URL.revokeObjectURL = () => {};
  const suspicious = { ...bundle, salary_deduction: { ...bundle.salary_deduction, orders: [
    { ...bundle.salary_deduction.orders[0], customer_name: '=HYPERLINK("https://invalid.example")', position: "+" + "Synthetic".repeat(30) },
  ] } };
  try {
    await downloadReport(suspicious, "daily", "excel");
    const ExcelJS = (await import("exceljs")).default;
    const workbook = new ExcelJS.Workbook(); await workbook.xlsx.load(await blob.arrayBuffer());
    const sheet = workbook.getWorksheet("SD Register");
    let found = false;
    sheet.eachRow(row => row.eachCell(cell => {
      if (cell.value === suspicious.salary_deduction.orders[0].customer_name) {
        found = true; assert.equal(cell.type, ExcelJS.ValueType.String); assert.equal(cell.formula, undefined); assert.equal(cell.alignment.wrapText, true);
      }
    }));
    assert.ok(found);
    await assert.rejects(downloadReport({ ...bundle, sales: { ...bundle.sales, period: { start: "../../bad", end: "2040-02-29" } } }, "daily", "excel"), /Invalid report period/);
  } finally { globalThis.document = previousDocument; URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke; }
});

test("PDF download creates a report with its period and sections", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response(readFileSync(new URL("../public/fonts/OpenSans-Regular.ttf", import.meta.url))));
  const pdf = await downloadReport(bundle, "daily", "pdf");
  assert.match(pdf.filename, /2040-02-29.*\.pdf$/);
  const output = pdf.document.output();
  assert.ok(output.startsWith("%PDF-"));
  assert.ok(pdf.document.getFontList().OpenSans);
  const font = pdf.document.getFont("OpenSans", "normal").metadata;
  assert.ok(font.characterToGlyph("ñ".codePointAt(0)));
  assert.ok(font.characterToGlyph("P".codePointAt(0)));
});

test("PDF handles multiple pages and embeds a Unicode font", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response(readFileSync(new URL("../public/fonts/OpenSans-Regular.ttf", import.meta.url))));
  const orders = Array.from({ length: 120 }, (_, i) => ({ ...bundle.salary_deduction.orders[0], order_id: i + 1, customer_name: "Synthetic long name ".repeat(6) }));
  const pdf = await downloadReport({ ...bundle, salary_deduction: { ...bundle.salary_deduction, orders } }, "weekly", "pdf");
  assert.ok(pdf.document.getNumberOfPages() > 1);
  assert.ok(pdf.document.getFontList().OpenSans);
});

test("changing report controls applies valid periods immediately and clears invalid selections", () => {
  const source = readFileSync(new URL("../src/components/reports-workspace.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } }).outputText;
  let index = 0; const updates = [];
  const states = [filter, filter, 0, null, false, "", ""];
  const jsx = (type, props) => ({ type, props });
  const exports = {};
  new Function("require", "exports", code)(name => name === "react" ? {
    useState: () => { const i = index++; return [states[i], value => updates.push([i, value])]; }, useEffect() {},
  } : name === "react/jsx-runtime" ? { jsx, jsxs: jsx } : {
    initialFilter, reportPath, loadReport, matchingEmployees, periodLabel,
  }, exports);
  const tree = exports.default({ request: async () => bundle }); const nodes = [];
  function visit(node) { if (!node || typeof node !== "object") return; if (Array.isArray(node)) return node.forEach(visit); nodes.push(node); visit(node.props?.children); }
  visit(tree);
  nodes.find(n => n.type === "select").props.onChange({ target: { value: "weekly" } });
  assert.ok(updates.some(([i, value]) => i === 1 && value?.mode === "weekly"));
  assert.ok(updates.some(([i, value]) => i === 3 && value === null));
  assert.ok(updates.some(([i, value]) => i === 4 && value === true));
  updates.length = 0;
  nodes.find(n => n.type === "input" && n.props.type === "date").props.onChange({ target: { value: "" } });
  assert.ok(updates.some(([i, value]) => i === 1 && value === null));
  assert.ok(updates.some(([i, value]) => i === 5 && value.includes("valid date")));
});
