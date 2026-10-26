import ExcelJS from "exceljs";
import type { ExportItem, ExportOrder, ExportReportBundle, ReportMode, SDOrder } from "./reports.ts";
import type { Payment } from "./api.ts";
import { paymentLabels } from "./meal.ts";
import { categoryLabels } from "./menus.ts";
import { insertNativeCharts, type NativeChart } from "./excel-charts.ts";

const NAVY = "FF160D76", BLUE = "FF4094D9", ORANGE = "FFF08530", WHITE = "FFFFFFFA", PALE = "FFEAF3FB";
const MONEY = '"₱"#,##0.00';
const methods: Payment[] = ["cash", "gcash", "sd", "incentive", "finance"];
const sheetNames = ["Executive Dashboard", "Daily Sales", "Salary Deduction List", "Mode of Payment"];
const zero = BigInt(0);
function ensure(condition: unknown): asserts condition {
  if (!condition) throw new Error("Report data is incomplete or does not reconcile. Refresh the report and try again.");
}
export function exactCents(value: string): bigint {
  ensure(typeof value === "string" && /^\d+\.\d{2}$/.test(value));
  return BigInt(value.replace(".", ""));
}
export function excelNumber(cents: bigint): number {
  const absolute = cents < zero ? -cents : cents;
  if (absolute > BigInt("999999999999999")) throw new Error("Report amounts exceed safe Excel numeric precision. No workbook was generated.");
  const value = Number(cents) / 100;
  if (Math.round(value * 100) !== Number(cents)) throw new Error("Report amounts cannot preserve exact cents in Excel.");
  return value;
}
const sum = <T,>(rows: T[], get: (row: T) => string) => rows.reduce((total, row) => total + exactCents(get(row)), zero);
const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
const key = (values: unknown[]) => JSON.stringify(values);
const itemKey = (i: { source_menu_item_id: number; item_name: string; category: string; unit_price: string }) => key([i.source_menu_item_id, i.item_name, i.category, i.unit_price]);
const snapshotKey = (o: SDOrder | ExportOrder) => key([o.employee_number, o.customer_name, o.campaign, o.position, o.line_of_business]);
const customerKey = (o: ExportOrder) => key([o.customer_type, o.employee_number, o.visitor_id, snapshotKey(o)]);

/** Independently check detail/summary consistency before any file is produced. */
export function validateExport(bundle: ExportReportBundle): void {
  const d = bundle.export_details, p = bundle.sales.period;
  ensure(d && /^\d{4}-\d{2}-\d{2}$/.test(p.start) && /^\d{4}-\d{2}-\d{2}$/.test(p.end));
  const start = Date.parse(p.start), end = Date.parse(p.end), days = (end - start) / 86400000 + 1;
  ensure(Number.isInteger(days) && days > 0 && days <= 3660);
  ensure(new Date(start).toISOString().slice(0, 10) === p.start && new Date(end).toISOString().slice(0, 10) === p.end);
  for (const period of [d.period, bundle.payments.period, bundle.salary_deduction.period]) ensure(period.start === p.start && period.end === p.end);
  ensure(d.daily.length === days && d.menu_dates.length === days);
  const orderIds = new Set<number>(), lineIds = new Set<number>(), sd = new Map<number, SDOrder>();
  ensure(count(bundle.sales.item_quantity) && count(bundle.sales.meal_quantity));
  const payments = new Map(methods.map(code => [code, zero]));
  const items = new Map<string, { quantity: number; amount: bigint }>();
  let meals = 0, quantity = 0;
  const menus = new Map(d.menus.map(m => [m.menu_id, m]));
  ensure(menus.size === d.menus.length);
  for (const order of d.orders) {
    ensure(Number.isSafeInteger(order.order_id) && !orderIds.has(order.order_id)); orderIds.add(order.order_id);
    ensure(order.service_date >= p.start && order.service_date <= p.end && menus.has(order.menu_id));
    ensure((order.customer_type === "employee" && typeof order.employee_number === "string" && order.visitor_id === null) ||
      (order.customer_type === "visitor" && order.employee_number === null && Number.isSafeInteger(order.visitor_id)));
    ensure(order.items.length && order.allocations.length);
    for (const item of order.items) {
      ensure(Number.isSafeInteger(item.order_item_id) && item.order_item_id > 0 && !lineIds.has(item.order_item_id)); lineIds.add(item.order_item_id);
      ensure(count(item.quantity) && item.quantity > 0 && Object.hasOwn(categoryLabels, item.category));
      ensure(exactCents(item.line_total) === exactCents(item.unit_price) * BigInt(item.quantity));
      quantity += item.quantity; if (item.category !== "extra_rice") meals += item.quantity;
      const previous = items.get(itemKey(item)) ?? { quantity: 0, amount: zero };
      items.set(itemKey(item), { quantity: previous.quantity + item.quantity, amount: previous.amount + exactCents(item.line_total) });
    }
    ensure(sum(order.items, i => i.line_total) === exactCents(order.total));
    ensure(sum(order.allocations, a => a.amount) === exactCents(order.total));
    const used = new Set<Payment>();
    for (const allocation of order.allocations) {
      ensure(methods.includes(allocation.category) && !used.has(allocation.category) && exactCents(allocation.amount) > zero);
      used.add(allocation.category);
      ensure(order.customer_type !== "visitor" || allocation.category === "finance");
      payments.set(allocation.category, payments.get(allocation.category)! + exactCents(allocation.amount));
      if (allocation.category === "sd") {
        ensure(order.employee_number !== null);
        sd.set(order.order_id, { order_id: order.order_id, service_date: order.service_date, employee_number: order.employee_number,
          customer_name: order.customer_name, campaign: order.campaign, position: order.position, line_of_business: order.line_of_business, sd_amount: allocation.amount });
      }
    }
  }
  ensure(count(bundle.sales.received_order_count) && d.orders.length === bundle.sales.received_order_count);
  ensure(quantity === bundle.sales.item_quantity && meals === bundle.sales.meal_quantity);
  ensure(sum(d.orders, o => o.total) === exactCents(bundle.sales.recognized_sales));
  ensure(exactCents(bundle.sales.recognized_sales) === exactCents(bundle.payments.total));
  ensure(items.size === bundle.sales.items.length && new Set(bundle.sales.items.map(itemKey)).size === items.size);
  for (const item of bundle.sales.items) ensure(items.get(itemKey(item))?.quantity === item.quantity && items.get(itemKey(item))?.amount === exactCents(item.amount));
  ensure(bundle.sales.categories.length === 3 && new Set(bundle.sales.categories.map(c => c.category)).size === 3);
  for (const category of bundle.sales.categories) {
    const lines = d.orders.flatMap(o => o.items).filter(i => i.category === category.category);
    ensure(category.quantity === lines.reduce((n, i) => n + i.quantity, 0) && exactCents(category.amount) === sum(lines, i => i.line_total));
  }
  const verifyPayments = (rows: { category: Payment; amount: string }[], expected: Map<Payment, bigint>) => {
    ensure(rows.length === 5 && new Set(rows.map(p => p.category)).size === 5);
    for (const payment of rows) ensure(expected.get(payment.category) === exactCents(payment.amount));
  };
  verifyPayments(bundle.payments.totals, payments);
  ensure([...payments.values()].reduce((a, b) => a + b, zero) === exactCents(bundle.payments.total));
  const campaigns = new Map<string | null, bigint>(), employees = new Map<string, { count: number; amount: bigint }>();
  ensure(sd.size === bundle.salary_deduction.orders.length);
  for (const order of bundle.salary_deduction.orders) {
    const source = sd.get(order.order_id);
    ensure(source && snapshotKey(source) === snapshotKey(order) && source.service_date === order.service_date && source.sd_amount === order.sd_amount);
    sd.delete(order.order_id);
    const previous = employees.get(order.employee_number) ?? { count: 0, amount: zero };
    employees.set(order.employee_number, { count: previous.count + 1, amount: previous.amount + exactCents(order.sd_amount) });
    campaigns.set(order.campaign, (campaigns.get(order.campaign) ?? zero) + exactCents(order.sd_amount));
  }
  ensure(employees.size === bundle.salary_deduction.employees.length && new Set(bundle.salary_deduction.employees.map(e => e.employee_number)).size === employees.size);
  for (const employee of bundle.salary_deduction.employees) ensure(exactCents(employee.sd_amount) > zero && employees.get(employee.employee_number)?.amount === exactCents(employee.sd_amount) && employees.get(employee.employee_number)?.count === employee.order_count);
  ensure(campaigns.size === d.sd_campaigns.length && new Set(d.sd_campaigns.map(c => c.campaign)).size === campaigns.size);
  for (const campaign of d.sd_campaigns) ensure(campaigns.get(campaign.campaign) === exactCents(campaign.sd_amount));
  ensure(sum(bundle.salary_deduction.orders, o => o.sd_amount) === payments.get("sd") && payments.get("sd") === exactCents(bundle.salary_deduction.total));
  for (let index = 0; index < days; index++) {
    const expectedDate = new Date(start + index * 86400000).toISOString().slice(0, 10), day = d.daily[index], menuDate = d.menu_dates[index];
    ensure(day.service_date === expectedDate && menuDate.service_date === expectedDate);
    ensure(menuDate.assigned_menu_id === null || menus.has(menuDate.assigned_menu_id));
    const orders = d.orders.filter(o => o.service_date === expectedDate);
    ensure(key(menuDate.recorded_menu_ids) === key([...new Set(orders.map(o => o.menu_id))].sort((a, b) => a - b)));
    ensure(day.received_order_count === orders.length && exactCents(day.recognized_sales) === sum(orders, o => o.total));
    ensure(day.item_quantity === orders.flatMap(o => o.items).reduce((n, i) => n + i.quantity, 0));
    ensure(day.meal_quantity === orders.flatMap(o => o.items).filter(i => i.category !== "extra_rice").reduce((n, i) => n + i.quantity, 0));
    const totals = new Map(methods.map(code => [code, sum(orders.flatMap(o => o.allocations).filter(a => a.category === code), a => a.amount)]));
    verifyPayments(day.payments, totals);
    ensure(exactCents(day.allocated_total) === exactCents(day.recognized_sales) && /^-?0\.00$/.test(day.allocation_difference));
  }
}

export function excelPeriodTitle(mode: ReportMode, start: string, end: string): string {
  const date = (s: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("en-PH", { ...options, timeZone: "UTC" }).format(new Date(`${s}T00:00:00Z`));
  const full = (s: string) => date(s, { month: "long", day: "numeric", year: "numeric" });
  if (mode === "daily") return `Daily Sales Report — ${full(start)}`;
  if (mode === "monthly") return `Monthly Sales Report — ${date(start, { month: "long", year: "numeric" })}`;
  const range = start.slice(0, 7) === end.slice(0, 7) ? `${date(start, { month: "long" })} ${Number(start.slice(8))}–${Number(end.slice(8))}, ${start.slice(0, 4)}` : `${full(start)} – ${full(end)}`;
  return `${mode === "weekly" ? "Weekly Sales Report" : "Sales Report"} — ${range}`;
}

const ref = (sheet: string, cell: string) => `'${sheet}'!${cell}`;
function text(cell: ExcelJS.Cell, value: string | null) {
  const s = value ?? "";
  if (s.length > 32767) throw new Error("Recorded text exceeds Excel's cell limit. No workbook was generated.");
  cell.value = s; cell.numFmt = "@"; cell.alignment = { vertical: "top", wrapText: true };
}
function money(cell: ExcelJS.Cell, value: bigint) { cell.value = excelNumber(value); cell.numFmt = MONEY; }
function formula(cell: ExcelJS.Cell, expression: string, cents: bigint) { cell.value = { formula: expression, result: excelNumber(cents) }; cell.numFmt = MONEY; }
function header(sheet: ExcelJS.Worksheet, row: number, labels: string[]) {
  const line = sheet.getRow(row);
  labels.forEach((label, i) => text(line.getCell(i + 1), label));
  line.font = { name: "Open Sans", bold: true, color: { argb: NAVY }, size: 10 };
  line.eachCell(cell => { cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: PALE } }; });
  line.height = 32;
}
function totalStyle(sheet: ExcelJS.Worksheet, row: number) {
  const line = sheet.getRow(row); line.font = { bold: true, name: "Open Sans", color: { argb: NAVY }, size: 10 };
  line.eachCell(cell => { cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFFDF0E5" } }; }); line.height = 30;
}
function finish(sheet: ExcelJS.Worksheet, headerRow: number, lastData: number, columns: number, freeze = 2) {
  sheet.unMergeCells("A2:M2"); sheet.mergeCells(2, 1, 2, columns);
  for (let c = 1; c <= columns; c++) if (!sheet.getColumn(c).width) sheet.getColumn(c).width = 22;
  sheet.views = [{ state: "frozen", xSplit: freeze, ySplit: headerRow, showGridLines: false }];
  sheet.autoFilter = { from: { row: headerRow, column: 1 }, to: { row: Math.max(headerRow, lastData), column: columns } };
  sheet.pageSetup.printTitlesRow = `${headerRow}:${headerRow}`;
  if (columns > 9) sheet.pageSetup.paperSize = 5;
  if (columns > 16) { sheet.pageSetup.fitToWidth = 0; sheet.pageSetup.printTitlesColumn = "A:B"; }
  sheet.pageSetup.printArea = `A1:${sheet.getColumn(columns).letter}${sheet.rowCount}`;
  sheet.eachRow(row => {
    let lines = 1;
    row.eachCell(cell => {
      cell.font = { name: "Open Sans", size: 10, ...cell.font };
      cell.alignment = { ...cell.alignment, vertical: "top", wrapText: true };
      if (typeof cell.value === "string" && !cell.isMerged) lines = Math.max(lines, cell.value.split("\n").reduce((n, line) => n + Math.ceil(line.length / Math.max(8, (sheet.getColumn(cell.col).width ?? 20) - 2)), 0));
    });
    if (15 * lines + 6 > 409) throw new Error("Recorded text is too long for readable Excel rows. No workbook was generated.");
    row.height = Math.max(row.height ?? 22, 15 * lines + 6);
  });
}
function blankState(sheet: ExcelJS.Worksheet, row: number, message: string) { text(sheet.getCell(row, 1), message); sheet.getRow(row).height = 30; }

function paymentSheet(sheet: ExcelJS.Worksheet, b: ExportReportBundle): number {
  text(sheet.getCell("A3"), "Reconciled · allocation arithmetic only");
  header(sheet, 5, ["Service date", ...methods.map(m => paymentLabels[m]), "Total allocated", "Recognized sales", "Difference"]);
  b.export_details.daily.forEach((day, index) => {
    const r = index + 6; text(sheet.getCell(r, 1), day.service_date);
    methods.forEach((method, i) => money(sheet.getCell(r, i + 2), exactCents(day.payments.find(p => p.category === method)!.amount)));
    formula(sheet.getCell(r, 7), `ROUND(SUM(B${r}:F${r}),2)`, exactCents(day.allocated_total));
    money(sheet.getCell(r, 8), exactCents(day.recognized_sales));
    formula(sheet.getCell(r, 9), `ROUND(H${r}-G${r},2)`, zero);
  });
  const end = b.export_details.daily.length + 5, total = end + 1;
  text(sheet.getCell(total, 1), "Period total");
  methods.forEach((method, i) => formula(sheet.getCell(total, i + 2), `ROUND(SUM(${sheet.getColumn(i + 2).letter}6:${sheet.getColumn(i + 2).letter}${end}),2)`, exactCents(b.payments.totals.find(p => p.category === method)!.amount)));
  formula(sheet.getCell(total, 7), `ROUND(SUM(B${total}:F${total}),2)`, exactCents(b.payments.total));
  formula(sheet.getCell(total, 8), `ROUND(SUM(H6:H${end}),2)`, exactCents(b.sales.recognized_sales));
  formula(sheet.getCell(total, 9), `ROUND(H${total}-G${total},2)`, zero);
  sheet.addConditionalFormatting({ ref: `I6:I${total}`, rules: [{ type: "expression", formulae: ["I6<>0"], priority: 1, style: { fill: { type: "pattern", pattern: "solid", fgColor: { argb: "FFFCE0DA" } }, font: { color: { argb: "FF9F291C" }, bold: true } } }] });
  totalStyle(sheet, total); finish(sheet, 5, end, 9, 1); return total;
}

function dailySheet(sheet: ExcelJS.Worksheet, b: ExportReportBundle) {
  const d = b.export_details;
  if (d.daily.length > 7) {
    text(sheet.getCell("A3"), "Recorded item ledger · Received orders only");
    const labels = ["Service date", "Order", "Customer reference", "Recorded customer", "Customer type", "Recorded campaign", "Recorded position", "Recorded LOB", "Recorded dish", "Category", "Unit price", "Quantity", "Line total"];
    header(sheet, 5, labels);
    let row = 6;
    for (const order of d.orders) for (const item of order.items) {
      const values = [order.service_date, `#${order.order_id}`, order.employee_number ?? `Visitor #${order.visitor_id}`, order.customer_name, order.customer_type, order.campaign, order.position, order.line_of_business, item.item_name, categoryLabels[item.category]];
      values.forEach((v, i) => text(sheet.getCell(row, i + 1), v));
      money(sheet.getCell(row, 11), exactCents(item.unit_price)); sheet.getCell(row, 12).value = item.quantity;
      formula(sheet.getCell(row, 13), `ROUND(K${row}*L${row},2)`, exactCents(item.line_total)); row++;
    }
    const end = row - 1;
    text(sheet.getCell(row, 1), "Period total"); formula(sheet.getCell(row, 13), end >= 6 ? `ROUND(SUM(M6:M${end}),2)` : "0", exactCents(b.sales.recognized_sales)); totalStyle(sheet, row++);
    const detailLastRow = row - 1;
    // Separate column ranges let Excel repeat row 5 using each section's own headers.
    // Keep the summary on this sheet without printing ledger headings above its dates.
    sheet.mergeCells("O1:P1"); text(sheet.getCell("O1"), "Daily sales summary");
    sheet.getCell("O1").font = { name: "Cardo", size: 16, bold: true, color: { argb: NAVY } };
    sheet.mergeCells("O2:P2"); text(sheet.getCell("O2"), `${b.sales.period.start} through ${b.sales.period.end}`);
    for (const [column, label] of [[15, "Service date"], [16, "Recognized sales"]] as const) {
      const cell = sheet.getCell(5, column); text(cell, label);
      cell.font = { name: "Open Sans", size: 10, bold: true, color: { argb: NAVY } };
      cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: PALE } };
    }
    sheet.getColumn(15).width = 20; sheet.getColumn(16).width = 22;
    row = 6;
    for (const day of d.daily) {
      text(sheet.getCell(row, 15), day.service_date);
      formula(sheet.getCell(row, 16), end >= 6 ? `ROUND(SUMIF(A$6:A$${end},O${row},M$6:M$${end}),2)` : "0", exactCents(day.recognized_sales)); row++;
    }
    text(sheet.getCell(row, 15), "Period total");
    formula(sheet.getCell(row, 16), `ROUND(SUM(P6:P${row - 1}),2)`, exactCents(b.sales.recognized_sales));
    for (const column of [15, 16]) sheet.getCell(row, column).font = { name: "Open Sans", size: 10, bold: true, color: { argb: NAVY } };
    if (!d.orders.length) blankState(sheet, detailLastRow + 1, "No Received orders in this period.");
    finish(sheet, 5, end, 13, 3);
    sheet.pageSetup.printArea = `A1:M${detailLastRow + (d.orders.length ? 0 : 1)}&&O1:P${row}`;
    return;
  }
  text(sheet.getCell("A3"), "Customer sales matrix · recorded quantities and prices");
  const groups = d.menu_dates.map(day => {
    const options = new Map<string, Omit<ExportItem, "order_item_id" | "line_number" | "quantity" | "line_total">>();
    const menu = d.menus.find(m => m.menu_id === day.assigned_menu_id);
    for (const item of menu?.offerings ?? []) {
      const variant = { ...item, source_menu_item_id: item.menu_item_id };
      options.set(itemKey(variant), variant);
    }
    for (const order of d.orders.filter(o => o.service_date === day.service_date)) for (const item of order.items) options.set(itemKey(item), item);
    return { date: day.service_date, items: [...options.values()].sort((a, b) => a.category.localeCompare(b.category) || a.item_name.localeCompare(b.item_name) || itemKey(a).localeCompare(itemKey(b))), start: 0, total: 0 };
  });
  const headings = ["Customer reference", "Recorded customer", "Type", "Recorded campaign", "Recorded position", "Recorded LOB"];
  let column = 7;
  for (const group of groups) {
    group.start = column;
    for (const item of group.items) {
      headings.push(`${item.item_name}\n${categoryLabels[item.category]} · ₱${excelNumber(exactCents(item.unit_price)).toFixed(2)}`);
      money(sheet.getCell(6, column++), exactCents(item.unit_price));
    }
    group.total = column; headings.push("Date total", "Payment"); column += 2;
    sheet.mergeCells(5, group.start, 5, column - 1);
    text(sheet.getCell(5, group.start), group.date);
    sheet.getCell(5, group.start).fill = { type: "pattern", pattern: "solid", fgColor: { argb: groups.indexOf(group) % 2 ? PALE : "FFD9E8F8" } };
  }
  if (column > 16384) throw new Error("This menu matrix exceeds Excel's column limit. Choose a shorter period.");
  headings.push("Period total"); header(sheet, 7, headings);
  const customers = new Map<string, ExportOrder[]>();
  for (const order of d.orders) customers.set(customerKey(order), [...(customers.get(customerKey(order)) ?? []), order]);
  let row = 8;
  for (const orders of customers.values()) {
    const order = orders[0];
    [order.employee_number ?? `Visitor #${order.visitor_id}`, order.customer_name, order.customer_type, order.campaign, order.position, order.line_of_business].forEach((v, i) => text(sheet.getCell(row, i + 1), v));
    for (const group of groups) {
      const dayOrders = orders.filter(o => o.service_date === group.date);
      if (!dayOrders.length) continue;
      group.items.forEach((item, index) => {
        const quantity = dayOrders.flatMap(o => o.items).filter(i => itemKey(i) === itemKey(item)).reduce((n, i) => n + i.quantity, 0);
        if (quantity) sheet.getCell(row, group.start + index).value = quantity;
      });
      const left = sheet.getColumn(group.start).letter, right = sheet.getColumn(group.total - 1).letter;
      formula(sheet.getCell(row, group.total), `ROUND(SUMPRODUCT(${left}${row}:${right}${row},${left}$6:${right}$6),2)`, sum(dayOrders, o => o.total));
      const payments = new Set(dayOrders.flatMap(o => o.allocations).map(a => a.category));
      text(sheet.getCell(row, group.total + 1), payments.size === 1 ? paymentLabels[[...payments][0]] : "Split");
    }
    formula(sheet.getCell(row, column), `ROUND(SUM(${groups.map(g => `${sheet.getColumn(g.total).letter}${row}`).join(",")}),2)`, sum(orders, o => o.total)); row++;
  }
  const end = row - 1;
  text(sheet.getCell(row, 1), "Period total");
  for (const group of groups) {
    group.items.forEach((item, index) => {
      const c = group.start + index, letter = sheet.getColumn(c).letter;
      const qty = d.orders.filter(o => o.service_date === group.date).flatMap(o => o.items).filter(i => itemKey(i) === itemKey(item)).reduce((n, i) => n + i.quantity, 0);
      sheet.getCell(row, c).value = { formula: end >= 8 ? `SUM(${letter}8:${letter}${end})` : "0", result: qty };
    });
    const letter = sheet.getColumn(group.total).letter;
    formula(sheet.getCell(row, group.total), end >= 8 ? `ROUND(SUM(${letter}8:${letter}${end}),2)` : "0", exactCents(d.daily.find(day => day.service_date === group.date)!.recognized_sales));
  }
  const letter = sheet.getColumn(column).letter;
  formula(sheet.getCell(row, column), end >= 8 ? `ROUND(SUM(${letter}8:${letter}${end}),2)` : "0", exactCents(b.sales.recognized_sales)); totalStyle(sheet, row);
  if (!d.orders.length) blankState(sheet, row + 1, "No Received orders in this period.");
  finish(sheet, 7, end, column); sheet.pageSetup.printTitlesRow = "5:7";
}

function sdSheet(sheet: ExcelJS.Worksheet, b: ExportReportBundle) {
  const orders = b.salary_deduction.orders, days = b.export_details.daily;
  text(sheet.getCell("A3"), `${b.salary_deduction.employees.length} employees with deductions · Reconciled`);
  sheet.mergeCells("A3:D3"); money(sheet.getCell("E3"), exactCents(b.salary_deduction.total));
  text(sheet.getCell("A4"), "Salary Deduction allocated does not indicate payroll completion."); sheet.mergeCells("A4:H4");
  let row = 6, columns = 0;
  if (days.length <= 31) {
    header(sheet, 5, ["Employee number", "Recorded employee", "Recorded campaign", "Position", "Line of business", ...days.map(d => `${d.service_date.slice(8)}\n${new Intl.DateTimeFormat("en", { month: "short", timeZone: "UTC" }).format(new Date(`${d.service_date}T00:00:00Z`))}`), "Period SD total"]);
    sheet.unMergeCells("A4:H4"); sheet.mergeCells("A4:B4");
    for (let first = 0; first < days.length;) {
      let last = first;
      while (last + 1 < days.length && days[last + 1].service_date.slice(0, 7) === days[first].service_date.slice(0, 7)) last++;
      if (last > first) sheet.mergeCells(4, first + 6, 4, last + 6);
      const cell = sheet.getCell(4, first + 6);
      text(cell, new Intl.DateTimeFormat("en", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${days[first].service_date}T00:00:00Z`)));
      cell.font = { name: "Open Sans", size: 10, bold: true, color: { argb: NAVY } };
      cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: PALE } };
      first = last + 1;
    }
    columns = 6 + days.length;
    const groups = new Map<string, SDOrder[]>();
    for (const order of orders) groups.set(snapshotKey(order), [...(groups.get(snapshotKey(order)) ?? []), order]);
    for (const group of groups.values()) {
      const first = group[0];
      [first.employee_number, first.customer_name, first.campaign, first.position, first.line_of_business].forEach((v, i) => text(sheet.getCell(row, i + 1), v));
      days.forEach((day, index) => {
        const values = group.filter(o => o.service_date === day.service_date);
        if (values.length) money(sheet.getCell(row, index + 6), sum(values, o => o.sd_amount));
      });
      formula(sheet.getCell(row, columns), `ROUND(SUM(F${row}:${sheet.getColumn(columns - 1).letter}${row}),2)`, sum(group, o => o.sd_amount)); row++;
    }
    for (let c = 6; c <= columns; c++) {
      const value = c === columns ? exactCents(b.salary_deduction.total) : sum(orders.filter(o => o.service_date === days[c - 6].service_date), o => o.sd_amount);
      const letter = sheet.getColumn(c).letter;
      formula(sheet.getCell(row, c), row > 6 ? `ROUND(SUM(${letter}6:${letter}${row - 1}),2)` : "0", value);
    }
  } else {
    header(sheet, 5, ["Service date", "Order", "Employee number", "Recorded employee", "Campaign", "Position", "Line of business", "SD allocated"]); columns = 8;
    for (const order of orders) {
      [order.service_date, `#${order.order_id}`, order.employee_number, order.customer_name, order.campaign, order.position, order.line_of_business].forEach((v, i) => text(sheet.getCell(row, i + 1), v));
      money(sheet.getCell(row++, 8), exactCents(order.sd_amount));
    }
    formula(sheet.getCell(row, 8), row > 6 ? `ROUND(SUM(H6:H${row - 1}),2)` : "0", exactCents(b.salary_deduction.total));
  }
  text(sheet.getCell(row, 1), "Period SD total"); totalStyle(sheet, row);
  if (!orders.length) blankState(sheet, row + 1, "No employees with Salary Deduction allocations in this period.");
  if (days.length <= 31) {
    [14, 27, 20, 22, 24].forEach((width, i) => { sheet.getColumn(i + 1).width = width; });
    for (let c = 6; c <= columns; c++) {
      let width = c === columns ? 14 : 10.5;
      sheet.getColumn(c).eachCell(cell => {
        const value = typeof cell.value === "number" ? cell.value : cell.result;
        if (typeof value === "number") width = Math.max(width, value.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).length + 3);
      });
      sheet.getColumn(c).width = width;
    }
  }
  finish(sheet, 5, row - 1, columns);
  if (days.length <= 31) {
    // Print the running period header rather than horizontal title fragments.
    sheet.pageSetup.printArea = `A4:${sheet.getColumn(columns).letter}${orders.length ? row : row + 1}`;
    sheet.getRow(4).height = 44;
    sheet.pageSetup.printTitlesRow = "4:5";
    sheet.pageSetup.printTitlesColumn = "A:B";
    sheet.pageSetup.fitToPage = false;
    sheet.pageSetup.fitToWidth = 0;
    sheet.pageSetup.scale = 100;
    sheet.pageSetup.margins = { left: 0.2, right: 0.2, top: 0.4, bottom: 0.4, header: 0.15, footer: 0.15 };
    sheet.headerFooter.oddHeader = `&LSalary Deduction ${b.sales.period.start} to ${b.sales.period.end}&REmployee identifiers repeat on continuation pages`;
  }
}

function dashboard(sheet: ExcelJS.Worksheet, b: ExportReportBundle, paymentTotalRow: number): NativeChart[] {
  sheet.unMergeCells("A1:H1"); sheet.mergeCells("A1:P1");
  sheet.unMergeCells("A2:M2"); sheet.mergeCells("A2:P2");
  const sales = exactCents(b.sales.recognized_sales), sd = exactCents(b.salary_deduction.total);
  sheet.columns = Array.from({ length: 16 }, () => ({ width: 11 }));
  const kpis: [string, string | number, bigint | null][] = [
    ["Recognized sales", ref("Mode of Payment", `H${paymentTotalRow}`), sales],
    ["Received orders", b.sales.received_order_count, null], ["Meals sold", b.sales.meal_quantity, null], ["Items sold", b.sales.item_quantity, null],
    ["Average order value", b.sales.received_order_count ? `ROUND(${ref("Mode of Payment", `H${paymentTotalRow}`)}/${b.sales.received_order_count},2)` : "—", b.sales.received_order_count ? (sales * BigInt(2) + BigInt(b.sales.received_order_count)) / (BigInt(2) * BigInt(b.sales.received_order_count)) : null],
    ["Salary Deduction", sd.toString(), sd], ["Total allocated", ref("Mode of Payment", `G${paymentTotalRow}`), exactCents(b.payments.total)], ["Reconciliation difference", ref("Mode of Payment", `I${paymentTotalRow}`), zero],
  ];
  kpis.forEach(([label, expression, amount], index) => {
    const r = index < 4 ? 4 : 8, c = (index % 4) * 4 + 1;
    sheet.mergeCells(r, c, r, c + 3); sheet.mergeCells(r + 1, c, r + 2, c + 3);
    text(sheet.getCell(r, c), label); sheet.getCell(r, c).font = { name: "Open Sans", size: 10, bold: true, color: { argb: BLUE } };
    const value = sheet.getCell(r + 1, c);
    if (amount !== null) {
      if (index === 5) money(value, amount); else formula(value, String(expression), amount);
    } else value.value = expression;
    value.font = { name: "Open Sans", size: 22, bold: true, color: { argb: NAVY } };
    value.fill = { type: "pattern", pattern: "solid", fgColor: { argb: PALE } };
  });
  sheet.mergeCells("A12:P12"); text(sheet.getCell("A12"), "Reconciled · recognized sales equal payment allocations");
  sheet.getCell("A12").font = { name: "Open Sans", bold: true, color: { argb: NAVY } };
  const top = [...b.sales.items].sort((a, other) => other.quantity - a.quantity || itemKey(a).localeCompare(itemKey(other)));
  const pay = [...b.payments.totals].sort((a, other) => exactCents(a.amount) === exactCents(other.amount) ? a.category.localeCompare(other.category) : exactCents(a.amount) > exactCents(other.amount) ? -1 : 1);
  const insights = [];
  if (top.length) insights.push(`Highest recorded item quantity: ${top[0].item_name.length > 90 ? "see first ranked item in source data" : top[0].item_name} (${top[0].quantity}).${top[1]?.quantity === top[0].quantity ? " Tied with other items." : ""}`);
  if (pay.length && exactCents(pay[0].amount) > zero) insights.push(`Largest allocated method: ${paymentLabels[pay[0].category]} (₱${excelNumber(exactCents(pay[0].amount)).toFixed(2)}).${pay[1]?.amount === pay[0].amount ? " Tied with another method." : ""}`);
  if (sales > zero) insights.push(`Salary Deduction represents ${Number((sd * BigInt(10000) + sales / BigInt(2)) / sales) / 100}% of recognized sales allocations.`);
  if (!insights.length) insights.push("No Received orders in this period.");
  insights.forEach((insight, i) => { sheet.mergeCells(14 + i, 1, 14 + i, 16); text(sheet.getCell(14 + i, 1), insight); sheet.getRow(14 + i).height = 32; });
  sheet.mergeCells("A55:P55"); text(sheet.getCell("A55"), "Chart source data · full recorded labels and numeric amounts");
  const charts: NativeChart[] = [];
  let sourceRow = 57;
  function source(title: string, labels: string[], values: number[], moneyValues: boolean, kind: "bar" | "line", slot: number, fullLabels = labels) {
    const first = sourceRow + 1, end = sourceRow + labels.length;
    header(sheet, sourceRow, [title, "Amount / quantity", "Full recorded label"]);
    labels.forEach((label, i) => {
      text(sheet.getCell(first + i, 1), label); sheet.getCell(first + i, 2).value = values[i];
      if (moneyValues) sheet.getCell(first + i, 2).numFmt = MONEY;
      text(sheet.getCell(first + i, 3), fullLabels[i]);
      sheet.mergeCells(first + i, 3, first + i, 10);
      sheet.getRow(first + i).height = Math.max(36, Math.min(409, Math.max(Math.ceil(fullLabels[i].length / 70), Math.ceil(label.length / 10)) * 15 + 6));
    });
    charts.push({ title, kind, labels, values, money: moneyValues, categoryRef: ref("Executive Dashboard", `$A$${first}:$A$${end}`), valueRef: ref("Executive Dashboard", `$B$${first}:$B$${end}`), seriesRef: ref("Executive Dashboard", `$B$${sourceRow}`), seriesName: "Amount / quantity",
      anchor: { left: slot % 2 ? 8 : 0, right: slot % 2 ? 16 : 8, top: slot < 2 ? 17 : 35, bottom: slot < 2 ? 34 : 52 } });
    sourceRow = end + 3;
  }
  const days = b.export_details.daily;
  if (days.length > 1) source("Daily recognized sales", days.map(d => d.service_date), days.map(d => excelNumber(exactCents(d.recognized_sales))), true, "line", 0);
  else source("Sales by recorded category", b.sales.categories.map(c => categoryLabels[c.category]), b.sales.categories.map(c => excelNumber(exactCents(c.amount))), true, "bar", 0);
  source("Payment allocations", methods.map(m => paymentLabels[m]), methods.map(m => excelNumber(exactCents(b.payments.totals.find(p => p.category === m)!.amount))), true, "bar", 1);
  if (top.length) {
    const ranked = top.slice(0, 10);
    const full = ranked.map(i => `${i.item_name} · ${categoryLabels[i.category]} · ₱${excelNumber(exactCents(i.unit_price)).toFixed(2)} · offering #${i.source_menu_item_id}`);
    source("Top recorded dishes by quantity", full.map((s, i) => s.length > 80 ? `Item ${i + 1} · full label below` : s), ranked.map(i => i.quantity), false, "bar", 2, full);
  } else { sheet.mergeCells("A37:H38"); text(sheet.getCell("A37"), "No recorded dishes to rank."); }
  if (b.export_details.sd_campaigns.length) {
    const campaigns = b.export_details.sd_campaigns;
    const full = campaigns.map(c => c.campaign === null ? "Not recorded (null)" : c.campaign === "" ? "Not recorded (blank)" : c.campaign);
    source("SD by recorded campaign", full.map((s, i) => s.length > 80 ? `Campaign ${i + 1} · full label below` : s), campaigns.map(c => excelNumber(exactCents(c.sd_amount))), true, "bar", 3, full);
  } else { sheet.mergeCells("I37:P38"); text(sheet.getCell("I37"), "No Salary Deduction allocations."); }
  sheet.views = [{ showGridLines: false }]; sheet.pageSetup.printArea = "A1:P53";
  // Keep all four dashboard charts together instead of splitting drawings across pages.
  sheet.pageSetup.fitToHeight = 1;
  sheet.getRow(1).height = 30;
  return charts;
}

export async function buildPremiumExcel(bundle: ExportReportBundle, mode: ReportMode): Promise<Uint8Array> {
  validateExport(bundle);
  // Refuse unsafe numeric inputs/aggregates before workbook creation, not after a partial download.
  for (const amount of [bundle.sales.recognized_sales, bundle.payments.total, bundle.salary_deduction.total, ...bundle.export_details.orders.flatMap(o => [o.total, ...o.items.flatMap(i => [i.unit_price, i.line_total])])]) excelNumber(exactCents(amount));
  const workbook = new ExcelJS.Workbook(); workbook.creator = "ASI Meal Management"; workbook.calcProperties.fullCalcOnLoad = true;
  const sheets = sheetNames.map((name, i) => {
    const sheet = workbook.addWorksheet(name, { properties: { tabColor: { argb: i === 0 ? NAVY : i === 2 ? ORANGE : BLUE } } });
    sheet.columns = Array.from({ length: 16 }, (_, col) => ({ width: col === 0 ? 20 : col === 1 || col === 3 ? 30 : 22 }));
    sheet.mergeCells("A1:H1"); text(sheet.getCell("A1"), `ASI Meal Management · ${name}`);
    sheet.getCell("A1").font = { name: "Cardo", size: 18, bold: true, color: { argb: WHITE } };
    sheet.getCell("A1").fill = { type: "pattern", pattern: "solid", fgColor: { argb: NAVY } }; sheet.getRow(1).height = 32;
    sheet.mergeCells("A2:M2"); text(sheet.getCell("A2"), `${excelPeriodTitle(mode, bundle.sales.period.start, bundle.sales.period.end)} · ${bundle.sales.period.start} through ${bundle.sales.period.end} · Philippine time, inclusive`); sheet.getRow(2).height = 34;
    sheet.pageSetup = { orientation: "landscape", paperSize: 9, fitToPage: true, fitToWidth: 1, fitToHeight: 0, margins: { left: 0.25, right: 0.25, top: 0.4, bottom: 0.4, header: 0.15, footer: 0.15 } };
    sheet.headerFooter.oddFooter = "&LASI Meal · Currently Received orders&RPage &P of &N";
    return sheet;
  });
  const paymentTotal = paymentSheet(sheets[3], bundle);
  dailySheet(sheets[1], bundle); sdSheet(sheets[2], bundle);
  const charts = dashboard(sheets[0], bundle, paymentTotal);
  const bytes = new Uint8Array(await workbook.xlsx.writeBuffer());
  return insertNativeCharts(bytes, "Executive Dashboard", charts);
}
