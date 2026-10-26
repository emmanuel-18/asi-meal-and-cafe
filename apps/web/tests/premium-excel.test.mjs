import test from "node:test";
import assert from "node:assert/strict";
import ExcelJS from "exceljs";
import JSZip from "jszip";
import { readFileSync } from "node:fs";
import ts from "typescript";
import * as reports from "../src/lib/reports.ts";
import * as meal from "../src/lib/meal.ts";
import * as menus from "../src/lib/menus.ts";
import { buildPremiumExcel, excelNumber, exactCents, excelPeriodTitle, validateExport } from "../src/lib/premium-excel.ts";
import { initialFilter, loadExportReport, loadReport } from "../src/lib/reports.ts";
import { ApiError } from "../src/lib/api.ts";
import { premiumFixture } from "./fixtures/premium-report.mjs";
import { insertNativeCharts } from "../src/lib/excel-charts.ts";

async function read(bundle, mode = "custom") {
  const bytes = await buildPremiumExcel(bundle, mode);
  const workbook = new ExcelJS.Workbook(); await workbook.xlsx.load(bytes);
  return { bytes, workbook, zip: await JSZip.loadAsync(bytes, { checkCRC32: true }) };
}

test("premium workbook has exactly four named sheets with full-period headers and adaptive 7/8 and 31/32 boundaries", async () => {
  for (const days of [1, 7, 8, 31, 32]) {
    const b = premiumFixture({ days }); const { workbook } = await read(b);
    assert.deepEqual(workbook.worksheets.map(s => s.name), ["Executive Dashboard", "Daily Sales", "Salary Deduction List", "Mode of Payment"]);
    for (const sheet of workbook.worksheets) {
      assert.match(sheet.getCell("A2").value, new RegExp(`${b.sales.period.start} through ${b.sales.period.end}`));
      assert.ok(sheet.pageSetup.printArea); assert.equal(sheet.pageSetup.orientation, "landscape");
    }
    const daily = workbook.worksheets[1], sd = workbook.worksheets[2];
    assert.equal(daily.views[0].ySplit, days <= 7 ? 7 : 5);
    assert.equal(sd.getCell("A5").value, days <= 31 ? "Employee number" : "Service date");
    assert.ok(daily.autoFilter); assert.ok(sd.autoFilter);
    assert.equal(workbook.worksheets[0].getCell("A5").result, Number(b.sales.recognized_sales));
  }
});

test("report headings use actual daily weekly monthly and cross-year custom periods", async () => {
  assert.equal(excelPeriodTitle("daily", "2026-10-23", "2026-10-23"), "Daily Sales Report — October 23, 2026");
  assert.equal(excelPeriodTitle("weekly", "2026-10-19", "2026-10-25"), "Weekly Sales Report — October 19–25, 2026");
  assert.equal(excelPeriodTitle("monthly", "2026-10-01", "2026-10-31"), "Monthly Sales Report — October 2026");
  assert.match(excelPeriodTitle("custom", "2026-12-30", "2027-01-02"), /2026.*2027/);
  for (const [mode, days, start] of [["daily", 1, "2026-10-23"], ["weekly", 7, "2026-10-19"], ["monthly", 31, "2026-10-01"], ["custom", 32, "2026-12-01"]]) {
    const b = premiumFixture({ days, start }); const { workbook } = await read(b, mode);
    assert.ok(workbook.worksheets[0].getCell("A2").value.startsWith(excelPeriodTitle(mode, b.sales.period.start, b.sales.period.end)));
  }
});

test("date-specific matrix retains historical prices, distinguishes blanks and uses SUMPRODUCT without duplicating revenue", async () => {
  const b = premiumFixture({ days: 2, historical: true }); const { workbook } = await read(b);
  const sheet = workbook.getWorksheet("Daily Sales");
  const headers = sheet.getRow(7).values;
  assert.ok(headers.some(v => String(v).includes("Historical renamed vegetable")));
  assert.ok(headers.some(v => String(v).includes("₱50.01")));
  assert.ok(headers.some(v => String(v).includes("₱50.00")));
  const firstDate = sheet.getRow(5).values.filter(v => typeof v === "string" && v.startsWith("2028"));
  assert.ok(firstDate.includes("2028-02-01") && firstDate.includes("2028-02-02"));
  let formulas = [];
  sheet.eachRow(row => row.eachCell(cell => { if (cell.formula) formulas.push(cell); }));
  assert.ok(formulas.some(c => c.formula.includes("SUMPRODUCT")));
  assert.ok(sheet.getColumn(1).values.includes("00001234"));
  assert.ok(sheet.getColumn(1).values.includes("Visitor #1"));
  assert.ok(sheet.getRow(8).values.includes("Split"));
  const footer = sheet.getRow(sheet.rowCount);
  assert.equal(footer.getCell(sheet.columnCount).result, Number(b.sales.recognized_sales));
  // A customer's absent date must not become a zero-price purchase.
  assert.ok(sheet.getRow(9).values.includes("Synthetic guest"));
  assert.equal(sheet.getCell(9, 7).value, null);
});

test("ledger and SD rows preserve identities and long formula-like text as strings, with nonzero SD only", async () => {
  const name = '=HYPERLINK("https://invalid.example")' + " Synthetic long ñ 長 name".repeat(20);
  const b = premiumFixture({ days: 32, name }); const { workbook } = await read(b);
  const ledger = workbook.worksheets[1], sd = workbook.worksheets[2];
  assert.equal(ledger.getCell("C6").value, "00001234"); assert.equal(ledger.getCell("C6").type, ExcelJS.ValueType.String);
  assert.equal(ledger.getCell("D6").value, name); assert.equal(ledger.getCell("D6").formula, undefined);
  assert.ok(ledger.getCell("D6").alignment.wrapText); assert.ok(ledger.getRow(6).height > 30);
  assert.equal(ledger.getCell("M6").formula, "ROUND(K6*L6,2)");
  assert.equal(sd.getCell("C6").value, "00001234");
  const ids = []; sd.eachRow((row, i) => { if (i >= 6) ids.push(row.getCell(3).value); });
  assert.ok(!ids.includes("00009999")); assert.ok(!ids.includes("Visitor #1"));
  assert.match(sd.getCell("A4").value, /does not indicate payroll completion/);
  const short = (await read(premiumFixture({ days: 7 }))).workbook.worksheets[2];
  assert.equal(short.getCell("A3").value, "1 employees with deductions · Reconciled");
  assert.equal(short.getCell("A6").value, "00001234");
  assert.equal(short.getCell("A7").value, "00001234"); // distinct campaign snapshot row
});

test("daily payment formulas preserve split allocations, all categories, numeric currency and exact period totals", async () => {
  const b = premiumFixture({ days: 7, historical: true }); const { workbook } = await read(b);
  const sheet = workbook.worksheets[3];
  assert.deepEqual(sheet.getRow(5).values.slice(2, 7), ["Cash", "GCash", "Salary Deduction", "Incentive", "Finance"]);
  assert.equal(sheet.getCell("G6").formula, "ROUND(SUM(B6:F6),2)");
  assert.equal(sheet.getCell("I6").formula, "ROUND(H6-G6,2)");
  assert.equal(sheet.getCell("B6").value, 35.01); assert.equal(sheet.getCell("D6").value, 30);
  assert.equal(sheet.getCell("B6").numFmt, '"₱"#,##0.00');
  assert.equal(sheet.getCell("G13").result, Number(b.payments.total));
  assert.equal(sheet.getCell("I13").result, 0);
});

test("native multi-chart package resolves numeric source ranges and retains all five payment methods", async () => {
  const { zip, workbook } = await read(premiumFixture({ days: 8 }));
  const chartParts = Object.keys(zip.files).filter(n => /^xl\/charts\/chart\d+\.xml$/.test(n));
  assert.equal(chartParts.length, 4);
  const chartXml = await Promise.all(chartParts.map(n => zip.file(n).async("string")));
  assert.ok(chartXml.some(s => s.includes("<c:lineChart>")));
  const payment = chartXml.find(s => s.includes("<a:t>Payment allocations</a:t>"));
  for (const label of ["Cash", "GCash", "Salary Deduction", "Incentive", "Finance"]) assert.ok(payment.includes(`<c:v>${label}</c:v>`));
  for (const xml of chartXml) {
    const values = [...xml.matchAll(/<c:val><c:numRef><c:f>&apos;Executive Dashboard&apos;!\$B\$(\d+):\$B\$(\d+)<\/c:f>/g)][0];
    assert.ok(values);
    const cache = /<c:numCache>(.*?)<\/c:numCache>/s.exec(xml)[1];
    const numbers = [...cache.matchAll(/<c:pt idx="\d+"><c:v>(.*?)<\/c:v><\/c:pt>/g)].map(m => Number(m[1]));
    assert.deepEqual(Array.from({ length: Number(values[2]) - Number(values[1]) + 1 }, (_, i) => workbook.worksheets[0].getCell(`B${Number(values[1]) + i}`).value), numbers);
  }
  const drawing = await zip.file("xl/drawings/drawing1.xml").async("string");
  assert.equal((drawing.match(/<xdr:twoCellAnchor>/g) ?? []).length, 4);
  const rels = await zip.file("xl/drawings/_rels/drawing1.xml.rels").async("string");
  for (let i = 1; i <= 4; i++) assert.ok(rels.includes(`Target="../charts/chart${i}.xml"`));
  for (const n of Object.keys(zip.files).filter(n => n.endsWith(".rels"))) assert.doesNotMatch(await zip.file(n).async("string"), /TargetMode="External"/);
  assert.ok(!Object.keys(zip.files).some(n => /xl\/media|vbaProject|externalLinks/.test(n)));
});

test("dashboard print settings keep its complete chart area on one landscape page", async () => {
  const { workbook } = await read(premiumFixture({ days: 31 }));
  const sheet = workbook.worksheets[0];
  assert.equal(sheet.pageSetup.printArea, "A1:P53");
  assert.equal(sheet.pageSetup.fitToWidth, 1);
  assert.equal(sheet.pageSetup.fitToHeight, 1);
  assert.equal(sheet.pageSetup.fitToPage, true);
  assert.equal(sheet.pageSetup.orientation, "landscape");
  assert.equal(workbook.worksheets[1].pageSetup.fitToHeight, 0);
});

test("ledger and daily summary have distinct print ranges with section-specific repeated headers", async () => {
  const b = premiumFixture({ days: 32 }), { workbook, zip } = await read(b);
  const sheet = workbook.worksheets[1];
  // ExcelJS's reader exposes only the first range of a standards-compliant union.
  // Inspect workbook XML below for the complete print-area definition.
  assert.match(sheet.pageSetup.printArea, /^A1:M\d+$/);
  assert.equal(sheet.pageSetup.printTitlesRow, "5:5");
  assert.equal(sheet.getCell("A5").value, "Service date"); assert.equal(sheet.getCell("B5").value, "Order");
  assert.equal(sheet.getCell("O5").value, "Service date"); assert.equal(sheet.getCell("P5").value, "Recognized sales");
  assert.equal(sheet.getCell("O6").value, b.sales.period.start);
  assert.match(sheet.getCell("P6").formula, /SUMIF\(A\$6:A\$\d+,O6,M\$6:M\$\d+\)/);
  assert.equal(sheet.getCell("P38").result, Number(b.sales.recognized_sales));
  assert.match(sheet.autoFilter, /^A5:M\d+$/);
  const xml = await zip.file("xl/workbook.xml").async("string");
  const names = [...xml.matchAll(/<definedName name="_xlnm.Print_Area" localSheetId="1">([^<]+)<\/definedName>/g)];
  assert.equal(names.length, 1); assert.match(names[0][1].replaceAll("&apos;", "'"), /\$A1:\$M\d+,'Daily Sales'!\$O1:\$P\d+/);
});

test("SD date matrix uses compact legible columns and repeated identifiers without changing totals", async () => {
  const b = premiumFixture({ days: 31, start: "2026-10-01" }), { workbook } = await read(b);
  const sheet = workbook.worksheets[2];
  assert.equal(sheet.getCell("F4").value, "October 2026"); assert.equal(sheet.getCell("F5").value, "01\nOct");
  assert.equal(sheet.getColumn(6).width, 10.5); assert.equal(sheet.getColumn(37).width, 14);
  assert.equal(sheet.getCell("F6").font.size, 10);
  assert.equal(sheet.pageSetup.printTitlesColumn, "A:B"); assert.equal(sheet.pageSetup.printTitlesRow, "4:5");
  assert.equal(sheet.pageSetup.scale, 100); assert.equal(sheet.pageSetup.fitToPage, false);
  assert.match(sheet.pageSetup.printArea, /^A4:AK\d+$/);
  assert.equal(sheet.getCell("B4").master.address, "A4");
  assert.equal(sheet.getCell("C4").isMerged, false);
  assert.equal(sheet.getRow(4).height, 44);
  assert.equal(sheet.getCell("E3").value, Number(b.salary_deduction.total));
  const crossMonth = (await read(premiumFixture({ days: 7, start: "2026-10-29" }))).workbook.worksheets[2];
  assert.equal(crossMonth.getCell("F4").value, "October 2026"); assert.equal(crossMonth.getCell("I4").value, "November 2026");
  const register = (await read(premiumFixture({ days: 32 }))).workbook.worksheets[2];
  assert.equal(register.getCell("H5").value, "SD allocated"); assert.equal(register.getCell("C6").value, "00001234");
});

test("chart insertion allocates drawing identities without changing other sheets, images, styles or values", async () => {
  const book = new ExcelJS.Workbook(), dashboard = book.addWorksheet("Executive Dashboard"), other = book.addWorksheet("Daily Sales");
  dashboard.getCell("A2").value = "Cash"; dashboard.getCell("B1").value = "Amount"; dashboard.getCell("B2").value = 0.01;
  other.getCell("D3").value = "00001234"; other.getCell("D3").numFmt = "@";
  const image = book.addImage({ base64: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==", extension: "png" });
  other.addImage(image, { tl: { col: 0, row: 0 }, ext: { width: 1, height: 1 } });
  const base = new Uint8Array(await book.xlsx.writeBuffer());
  const result = await insertNativeCharts(base, "Executive Dashboard", [{ title: "Payment", kind: "bar", labels: ["Cash"], values: [0.01], money: true,
    categoryRef: "'Executive Dashboard'!$A$2:$A$2", valueRef: "'Executive Dashboard'!$B$2:$B$2", seriesRef: "'Executive Dashboard'!$B$1", seriesName: "Amount", anchor: { left: 0, top: 4, right: 8, bottom: 15 } }]);
  const before = await JSZip.loadAsync(base), after = await JSZip.loadAsync(result);
  for (const [name, file] of Object.entries(before.files)) {
    if (file.dir || name === "xl/worksheets/sheet1.xml" || name === "[Content_Types].xml") continue;
    assert.deepEqual(await after.file(name).async("uint8array"), await file.async("uint8array"), name);
  }
  assert.ok(after.file("xl/drawings/drawing2.xml"));
  await assert.rejects(insertNativeCharts(result, "Executive Dashboard", []), /already contains/);
});

test("empty export has four usable sheets, no fabricated rankings and no SD employee rows", async () => {
  const { workbook, zip } = await read(premiumFixture({ days: 1, empty: true }));
  assert.equal(workbook.worksheets[0].getCell("A9").value, "—");
  assert.equal(workbook.worksheets[0].getCell("A14").value, "No Received orders in this period.");
  assert.equal(workbook.worksheets[2].getCell("A6").value, "Period SD total");
  assert.equal(Object.keys(zip.files).filter(n => /^xl\/charts\/chart\d+\.xml$/.test(n)).length, 2);
});

test("malformed, duplicate, non-reconciled, incomplete-period or unsafe values never yield a workbook", async () => {
  for (const mutate of [b => b.sales.recognized_sales = "0.00", b => b.payments.total = "0.00", b => b.salary_deduction.total = "0.00",
    b => b.export_details.daily.pop(), b => b.export_details.orders.push(b.export_details.orders[0]),
    b => b.export_details.orders[0].items[0].line_total = "1.00", b => b.export_details.sd_campaigns[0].sd_amount = "0.00",
    b => b.export_details.orders[1].allocations[0].category = "cash", b => b.export_details.period = { start: "2020-01-01", end: "2020-01-02" }]) {
    const b = premiumFixture(); mutate(b); await assert.rejects(buildPremiumExcel(b, "daily"));
  }
  assert.equal(excelNumber(exactCents("0.01")), 0.01);
  assert.throws(() => excelNumber(exactCents("9999999999999999.01")), /precision/);
  assert.throws(() => exactCents("1.001"));
  const b = premiumFixture(); delete b.export_details; assert.throws(() => validateExport(b));
});

test("only Excel request opts into full-period details and reports HTTP 409 explicitly", async () => {
  const b = premiumFixture(), filter = { ...initialFilter(), day: b.sales.period.start };
  const calls = [], controller = new AbortController();
  const request = async (path, init) => { calls.push([path, init]); return b; };
  await loadReport(request, filter); await loadExportReport(request, filter, b.sales.period, controller.signal);
  assert.ok(!calls[0][0].includes("include_export_details"));
  assert.match(calls[1][0], /include_export_details=true/);
  assert.ok(!calls[1][0].includes("employee")); assert.equal(calls[1][1].signal, controller.signal);
  await assert.rejects(loadExportReport(async () => { throw new ApiError(409, "Conflict"); }, filter, b.sales.period), /reconciled/);
  await assert.rejects(loadExportReport(request, filter, { start: "2000-01-01", end: "2040-01-01" }), /3,660/);
});

function workspaceHarness(request, downloads, bundle = premiumFixture(), options = {}) {
  const source = readFileSync(new URL("../src/components/reports-workspace.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } }).outputText;
  const filter = { ...initialFilter(), day: (bundle ?? premiumFixture()).sales.period.start };
  const states = [filter, filter, 0, bundle, options.loading ?? false, "", "employee search matches nothing", options.exporting ?? false], updates = [], run = { current: null };
  let index = 0;
  const jsx = (type, props) => ({ type, props }), exports = {};
  new Function("require", "exports", code)(name => {
    if (name === "react") return { useState: () => { const i = index++; return [states[i], value => updates.push([i, value])]; }, useEffect() {}, useRef: () => run };
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
    if (name === "@/lib/reports") return reports;
    if (name === "@/lib/meal") return meal;
    if (name === "@/lib/menus") return menus;
    if (name === "@/lib/report-export") return { downloadReport: async (...args) => { downloads.push(args); } };
    return {};
  }, exports);
  const tree = exports.default({ request }), nodes = [];
  function visit(n) { if (!n || typeof n !== "object") return; if (Array.isArray(n)) return n.forEach(visit); nodes.push(n); visit(n.props?.children); }
  visit(tree);
  return { nodes, trigger: nodes.find(n => n.type === "button" && n.props.className === "report-download-excel"), period: nodes.find(n => n.type === "select"), updates, run };
}

test("workspace Excel action fetches once on demand, ignores employee search and uses the fresh response snapshot", async () => {
  const downloads = [], calls = [], fresh = premiumFixture({ historical: true });
  const view = workspaceHarness(async path => { calls.push(path); return fresh; }, downloads);
  assert.equal(calls.length, 0);
  view.trigger.props.onClick(); view.trigger.props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 1); assert.match(calls[0], /include_export_details=true/); assert.ok(!calls[0].includes("search"));
  assert.equal(downloads.length, 1); assert.equal(downloads[0][0], fresh); assert.equal(downloads[0][2], "excel");
});

test("workspace cancels a late Excel response after period change and exposes reconciliation failures", async () => {
  const downloads = []; let complete;
  const view = workspaceHarness(() => new Promise(resolve => { complete = resolve; }), downloads);
  view.trigger.props.onClick();
  view.period.props.onChange({ target: { value: "weekly" } });
  complete(premiumFixture()); await new Promise(resolve => setImmediate(resolve));
  assert.equal(downloads.length, 0);
  const failed = workspaceHarness(async () => { throw new ApiError(409, "Conflict"); }, downloads);
  failed.trigger.props.onClick(); await new Promise(resolve => setImmediate(resolve));
  assert.ok(failed.updates.some(([i, value]) => i === 5 && value.includes("could not be reconciled")));
  assert.equal(downloads.length, 0);
});

test("workspace offers only one Excel download with loading feedback and no PDF or menu control", () => {
  const view = workspaceHarness(async () => premiumFixture(), []);
  assert.equal(view.nodes.filter(n => n.props?.className === "report-download-excel").length, 1);
  assert.equal(view.trigger.props.type, "button");
  assert.equal(view.trigger.props.disabled, false);
  assert.equal(view.trigger.props["aria-busy"], false);
  assert.equal(view.trigger.props["aria-haspopup"], undefined);
  assert.ok(view.trigger.props.children.includes("Download Excel"));
  assert.equal(view.nodes.filter(n => n.props?.role === "menu" || n.props?.role === "menuitem").length, 0);
  for (const options of [{ loading: true }, { exporting: true }]) {
    const busy = workspaceHarness(async () => premiumFixture(), [], premiumFixture(), options);
    assert.equal(busy.trigger.props.disabled, true);
    assert.equal(busy.trigger.props["aria-busy"], !!options.exporting);
    if (options.exporting) assert.ok(busy.trigger.props.children.includes("Preparing Excel..."));
  }
  const empty = workspaceHarness(async () => premiumFixture(), [], null);
  assert.equal(empty.trigger.props.disabled, true);
});
