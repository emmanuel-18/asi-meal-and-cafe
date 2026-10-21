import type { Allocation, Menu, OrderInput, Payment, Role } from "./api";

export const paymentLabels: Record<Payment, string> = {
  cash: "Cash", gcash: "GCash", sd: "Salary Deduction", incentive: "Incentive", finance: "Finance",
};
export const reasons = [
  ["mistaken_click", "Mistaken click"], ["incorrect_employee_marked", "Incorrect employee marked"],
  ["incorrect_order_marked", "Incorrect order marked"], ["incorrect_order_details", "Incorrect order details"],
  ["other", "Other reason"],
] as const;
export type Reason = typeof reasons[number][0];

// Preview arithmetic uses integer centavos. Saved amounts always come from the API.
export function centavos(value: string, bounded = true): bigint | null {
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  const result = BigInt(whole) * BigInt(100) + BigInt(fraction.padEnd(2, "0"));
  return !bounded || result <= BigInt("999999999999") ? result : null;
}
export function decimal(value: bigint): string {
  const sign = value < BigInt(0) ? "-" : "";
  const absolute = value < BigInt(0) ? -value : value;
  return `${sign}${absolute / BigInt(100)}.${String(absolute % BigInt(100)).padStart(2, "0")}`;
}
export function pesos(value: string | bigint): string {
  const amount = typeof value === "bigint" ? value : centavos(value, false);
  if (amount === null) return "—";
  const [whole, fraction] = decimal(amount).split(".");
  return `₱${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction}`;
}
export function itemTotal(menu: Menu, quantities: Record<number, number>): bigint {
  return menu.items.reduce((sum, item) => {
    const quantity = quantities[item.id] ?? 0;
    if (!Number.isInteger(quantity) || quantity < 0 || quantity > 2147483647) throw new Error("Invalid quantity");
    const price = centavos(item.unit_price);
    if (price === null) throw new Error("Invalid offering price");
    return sum + price * BigInt(quantity);
  }, BigInt(0));
}
export function allocationTotal(allocations: Allocation[]): bigint | null {
  let sum = BigInt(0);
  for (const allocation of allocations) {
    const value = centavos(allocation.amount);
    if (value === null || value === BigInt(0)) return null;
    sum += value;
  }
  return sum;
}
export function buildOrder(key: string, menu: Menu, quantities: Record<number, number>,
  customer: { employee_number: string } | { visitor_id: number }, allocations: Allocation[]): OrderInput {
  itemTotal(menu, quantities);
  const items = menu.items.filter(i => (quantities[i.id] ?? 0) > 0)
    .map(i => ({ menu_item_id: i.id, quantity: quantities[i.id] }));
  if (!items.length || allocationTotal(allocations) === null) throw new Error("Select items and valid allocation amounts.");
  if ("visitor_id" in customer && allocations.some(a => a.category !== "finance")) throw new Error("Visitors use Finance only.");
  return { request_key: key, service_date: menu.service_date, menu_id: menu.id, ...customer, items, allocations };
}
export function canReverse(role: Role, received: boolean): boolean { return role === "admin" && received; }
export function canConfirm(reason: Reason, explanation: string, acknowledged: boolean): boolean {
  return acknowledged && (reason !== "other" || explanation.trim().length > 0);
}
export function operationalToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}
