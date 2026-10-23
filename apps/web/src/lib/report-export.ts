import type { ReportBundle, ReportMode } from "./reports.ts";
import { periodLabel } from "./reports.ts";
import { centavos, paymentLabels, pesos } from "./meal.ts";
import { categoryLabels } from "./menus.ts";

type Section = { title: string; headers: string[]; rows: string[][] };

export function paymentBarWidth(value: bigint | null, maximum: bigint): number {
  if (value === null || value <= BigInt(0) || maximum <= BigInt(0)) return 0;
  return Number((value * BigInt(10000)) / maximum) / 100 * 1.05;
}

export function excelMoney(value: string): number | null {
  const match = /^₱([\d,]+)\.(\d{2})$/.exec(value);
  if (!match) return null;
  const cents = BigInt(match[1].replace(/,/g, "") + match[2]);
  if (cents > BigInt("999999999999999")) return null;
  const number = Number(cents) / 100;
  return Math.round(number * 100) === Number(cents) ? number : null;
}

export function reportSections(bundle: ReportBundle): Section[] {
  return [
    { title: "Sales summary", headers: ["Measure", "Value"], rows: [
      ["Recognized sales", pesos(bundle.sales.recognized_sales)], ["Received orders", String(bundle.sales.received_order_count)],
      ["Meals", String(bundle.sales.meal_quantity)], ["Items", String(bundle.sales.item_quantity)] ] },
    { title: "Sales by category", headers: ["Category", "Quantity", "Sales"], rows: bundle.sales.categories.map(row => [categoryLabels[row.category], String(row.quantity), pesos(row.amount)]) },
    { title: "Recorded item sales", headers: ["Item", "Category", "Unit price", "Quantity", "Sales"], rows: bundle.sales.items.map(item => [item.item_name, categoryLabels[item.category], pesos(item.unit_price), String(item.quantity), pesos(item.amount)]) },
    { title: "Payment allocations", headers: ["Category", "Allocated amount"], rows: [...bundle.payments.totals.map(row => [paymentLabels[row.category], pesos(row.amount)]), ["Total allocated", pesos(bundle.payments.total)]] },
    { title: "Salary Deduction summary", headers: ["Measure", "Amount"], rows: [["Total SD allocated", pesos(bundle.salary_deduction.total)]] },
    { title: "Salary Deduction orders", headers: ["Date", "Order", "Employee number", "Recorded name", "Position", "Campaign", "Line of business", "SD amount"], rows: bundle.salary_deduction.orders.map(order => [order.service_date, String(order.order_id), order.employee_number, order.customer_name, order.position ?? "", order.campaign ?? "", order.line_of_business ?? "", pesos(order.sd_amount)]) },
  ];
}

export async function downloadReport(bundle: ReportBundle, mode: ReportMode, format: "excel" | "pdf") {
  const period = bundle.sales.period;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(period.start) || !/^\d{4}-\d{2}-\d{2}$/.test(period.end)) {
    throw new Error("Invalid report period.");
  }
  const heading = periodLabel(mode, period);
  const filename = `asi-meal-report-${period.start}-to-${period.end}`;
  const sections = reportSections(bundle);
  const salesCents = centavos(bundle.sales.recognized_sales, false);
  const allocatedCents = centavos(bundle.payments.total, false);
  const reconciliation = salesCents === null || allocatedCents === null ? "Unavailable" : salesCents === allocatedCents ? "Balanced" : "Difference detected";
  if (format === "excel") {
    const { default: ExcelJS } = await import("exceljs");
    const workbook = new ExcelJS.Workbook();
    const overview = workbook.addWorksheet("Executive Overview");
    const detail = workbook.addWorksheet("Detailed Report");
    const register = workbook.addWorksheet("SD Register");
    for (const sheet of [overview, detail, register]) {
      sheet.addRow(["ASI Meal Management - Report"]); sheet.addRow([heading]);
      sheet.addRow(["Currently Received orders only. SD allocations do not indicate payroll completion."]);
      sheet.getRow(1).font = { bold: true, size: 16, color: { argb: "FF160D76" } };
      sheet.views = [{ state: "frozen", ySplit: 3 }];
      sheet.pageSetup = { orientation: "landscape", fitToPage: true, fitToWidth: 1, fitToHeight: 0 };
      sheet.columns = Array.from({ length: 8 }, () => ({ width: 23 }));
    }
    overview.addRow([]);
    overview.addRow(["Payment reconciliation", reconciliation]);
    overview.addRow(["Received orders", bundle.sales.received_order_count]);
    overview.addRow(["Meals", bundle.sales.meal_quantity]);
    overview.addRow(["Items", bundle.sales.item_quantity]);
    for (const [label, amount] of [["Recognized sales", bundle.sales.recognized_sales], ["Total allocated", bundle.payments.total], ["Salary Deduction", bundle.salary_deduction.total]]) {
      const row = overview.addRow([label, pesos(amount)]);
      const number = excelMoney(pesos(amount));
      if (number !== null) { row.getCell(2).value = number; row.getCell(2).numFmt = '"₱"#,##0.00'; }
    }
    overview.addRow(["Report basis", "Currently Received orders"]);
    for (const [sheet, section] of [[overview, sections[1]], [overview, sections[3]], ...sections.slice(0, 5).map(section => [detail, section] as const), [register, sections[5]]] as const) {
      sheet.addRow([]); const title = sheet.addRow([section.title]); title.font = { bold: true, color: { argb: "FF160D76" } };
      const header = sheet.addRow(section.headers); header.font = { bold: true };
      for (const row of section.rows) {
        const added = sheet.addRow(row);
        added.eachCell(cell => { cell.alignment = { wrapText: true, vertical: "top" }; });
        const moneyColumns: Record<string, number[]> = {
          "Sales by category": [3], "Recorded item sales": [3, 5], "Payment allocations": [2],
          "Salary Deduction summary": [2], "Salary Deduction orders": [8],
        };
        const columns = section.title === "Sales summary" && row[0] === "Recognized sales" ? [2] : moneyColumns[section.title] ?? [];
        for (const column of columns) {
          const amount = excelMoney(row[column - 1]);
          if (amount !== null) { const cell = added.getCell(column); cell.value = amount; cell.numFmt = '"₱"#,##0.00'; }
        }
      }
      if (!section.rows.length) sheet.addRow(["No records for this period."]);
    }
    register.views = [{ state: "frozen", ySplit: 6 }];
    register.columns = [18, 14, 20, 30, 24, 26, 26, 20].map(width => ({ width }));
    register.autoFilter = { from: "A6", to: "H6" };
    const bytes = await workbook.xlsx.writeBuffer();
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    const link = document.createElement("a"); link.href = url; link.download = `${filename}.xlsx`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } else {
    const { jsPDF } = await import("jspdf");
    const { default: autoTable } = await import("jspdf-autotable");
    const doc = new jsPDF({ orientation: "landscape" });
    const response = await fetch("/fonts/OpenSans-Regular.ttf");
    if (!response.ok) throw new Error("PDF font unavailable");
    const bytes = new Uint8Array(await response.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    doc.addFileToVFS("OpenSans-Regular.ttf", btoa(binary));
    doc.addFont("OpenSans-Regular.ttf", "OpenSans", "normal");
    doc.addFont("OpenSans-Regular.ttf", "OpenSans", "bold");
    doc.setFont("OpenSans", "normal");
    doc.setFontSize(16); doc.text("ASI Meal Management - Report", 14, 15);
    doc.setFontSize(10); doc.text(heading.replace(/[–—]/g, "-"), 14, 22);
    doc.text("Currently Received orders only. SD allocations do not indicate payroll completion.", 14, 28);
    autoTable(doc, { startY: 34, head: [["Executive summary", "Value"]], body: [
      ["Recognized sales", pesos(bundle.sales.recognized_sales).replace(/₱/g, "PHP ")],
      ["Received orders", String(bundle.sales.received_order_count)],
      ["Meals / items", `${bundle.sales.meal_quantity} / ${bundle.sales.item_quantity}`],
      ["Total allocated", pesos(bundle.payments.total).replace(/₱/g, "PHP ")],
      ["Salary Deduction", pesos(bundle.salary_deduction.total).replace(/₱/g, "PHP ")],
      ["Payment reconciliation", reconciliation],
    ], styles: { font: "OpenSans", fontSize: 9 }, headStyles: { fillColor: [22, 13, 118] } });
    const payments = bundle.payments.totals.map(row => ({ ...row, cents: centavos(row.amount, false) }));
    const maxPayment = payments.reduce((max, row) => row.cents !== null && row.cents > max ? row.cents : max, BigInt(0));
    const chartY = (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 10;
    doc.setTextColor(22, 13, 118); doc.setFontSize(11); doc.text("Payment allocations", 14, chartY);
    doc.setFontSize(8);
    payments.forEach((row, index) => {
      const y = chartY + 7 + index * 9;
      doc.setTextColor(34, 34, 34); doc.text(paymentLabels[row.category], 14, y);
      doc.setFillColor(235, 238, 247); doc.rect(66, y - 3, 105, 4, "F");
      if (row.cents !== null && maxPayment > BigInt(0)) {
        const width = paymentBarWidth(row.cents, maxPayment);
        if (width > 0) { doc.setFillColor(64, 148, 217); doc.rect(66, y - 3, width, 4, "F"); }
      }
      doc.text(pesos(row.amount).replace(/₱/g, "PHP "), 177, y);
    });
    doc.setTextColor(34, 34, 34);
    doc.addPage();
    let y = 15;
    for (const section of sections) {
      if (y > 180) { doc.addPage(); y = 15; }
      doc.setFontSize(12); doc.text(section.title, 14, y);
      autoTable(doc, { startY: y + 3, head: [section.headers], body: section.rows.length ? section.rows.map(row => row.map(value => value.replace(/₱/g, "PHP "))) : [["No records for this period."]], styles: { font: "OpenSans", fontSize: 8, overflow: "linebreak" }, headStyles: { fillColor: [22, 13, 118] }, columnStyles: section.title === "Salary Deduction orders" ? { 7: { cellWidth: 24 } } : section.title === "Recorded item sales" ? { 2: { cellWidth: 24 }, 4: { cellWidth: 24 } } : {}, showHead: "everyPage" });
      y = (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 10;
    }
    const pageCount = doc.getNumberOfPages();
    for (let page = 1; page <= pageCount; page++) {
      doc.setPage(page); doc.setFont("OpenSans", "normal"); doc.setFontSize(8);
      doc.text(`${period.start} to ${period.end} · Page ${page} of ${pageCount}`, 14, doc.internal.pageSize.getHeight() - 7);
    }
    return { document: doc, filename: `${filename}.pdf` };
  }
}
