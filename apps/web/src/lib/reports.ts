import type { Category, Payment, RequestApi } from "./api.ts";

export type ReportMode = "daily" | "weekly" | "monthly" | "custom";
export type ReportFilter = { mode: ReportMode; day: string; month: string; start: string; end: string };
export type Period = { start: string; end: string };
export type SDOrder = { order_id: number; service_date: string; employee_number: string; customer_name: string;
  position: string | null; campaign: string | null; line_of_business: string | null; sd_amount: string };
export type ReportBundle = {
  sales: { period: Period; recognized_sales: string; received_order_count: number; item_quantity: number; meal_quantity: number;
    categories: { category: Category; quantity: number; amount: string }[];
    items: { source_menu_item_id: number; item_name: string; category: Category; unit_price: string; quantity: number; amount: string }[] };
  payments: { period: Period; totals: { category: Payment; amount: string }[]; total: string };
  salary_deduction: { period: Period; total: string; employees: { employee_number: string; order_count: number; sd_amount: string }[]; orders: SDOrder[] };
};

export function manilaDate(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const value = (name: string) => parts.find(part => part.type === name)?.value ?? "";
  return `${value("year").padStart(4, "0")}-${value("month")}-${value("day")}`;
}

export function initialFilter(now?: Date): ReportFilter {
  const today = manilaDate(now);
  return { mode: "daily", day: today, month: today.slice(0, 7), start: today, end: today };
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

export function reportPath(filter: ReportFilter): string {
  const params = new URLSearchParams({ mode: filter.mode });
  if (filter.mode === "daily" || filter.mode === "weekly") {
    if (!validDate(filter.day)) throw new Error("Choose a valid date.");
    params.set("day", filter.day);
  } else if (filter.mode === "monthly") {
    if (!/^\d{4}-\d{2}$/.test(filter.month) || !validDate(`${filter.month}-01`)) throw new Error("Choose a valid month.");
    const [year, month] = filter.month.split("-");
    params.set("year", String(Number(year))); params.set("month", String(Number(month)));
  } else if (filter.mode === "custom") {
    if (!validDate(filter.start) || !validDate(filter.end) || filter.start > filter.end) throw new Error("Choose valid dates with the start on or before the end.");
    params.set("start", filter.start); params.set("end", filter.end);
  } else throw new Error("Choose a reporting period.");
  return `/api/reports/bundle?${params}`;
}

export function loadReport(request: RequestApi, filter: ReportFilter, signal?: AbortSignal): Promise<ReportBundle> {
  return request<ReportBundle>(reportPath(filter), { signal });
}

export function matchingEmployees(bundle: ReportBundle, query: string) {
  const term = query.trim().toLocaleLowerCase();
  return bundle.salary_deduction.employees.filter(employee => !term || employee.employee_number.toLocaleLowerCase().includes(term) ||
    bundle.salary_deduction.orders.some(order => order.employee_number === employee.employee_number && order.customer_name.toLocaleLowerCase().includes(term)));
}
