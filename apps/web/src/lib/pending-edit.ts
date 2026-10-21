import type { Allocation, Offering, OrderDetail, OrderResult, Payment, PendingEdit, RequestApi, Role } from "./api";
import { centavos } from "./meal.ts";

export type DraftLine = {
  key: string; lineId: number | null; offeringId: number; name: string; category: string; unitPrice: string; quantity: string;
};
export type PendingDraft = { lines: DraftLine[]; split: boolean; single: Payment; amounts: Partial<Record<Payment, string>> };
const codes: Payment[] = ["cash", "gcash", "sd", "incentive", "finance"];

export function canEditPending(role: Role, received: boolean): boolean {
  return !received && (role === "admin" || role === "assistant_admin");
}
export function createDraft(order: OrderDetail): PendingDraft {
  if (order.is_received) throw new Error("Received orders cannot be edited. Reload the latest order.");
  return {
    lines: order.items.map(i => ({ key: `saved-${i.id}`, lineId: i.id, offeringId: i.source_menu_item_id,
      name: i.name, category: i.category, unitPrice: i.unit_price, quantity: String(i.quantity) })),
    split: order.allocations.length > 1,
    single: order.visitor_id !== null ? "finance" : order.allocations[0]?.category ?? "cash",
    amounts: Object.fromEntries(order.allocations.map(a => [a.category, a.amount])),
  };
}
export function offeringLine(offering: Offering, key: string, quantity = "1"): DraftLine {
  return { key, lineId: null, offeringId: offering.id, name: offering.item_name, category: offering.category_code,
    unitPrice: offering.unit_price, quantity };
}
export function replaceLine(draft: PendingDraft, key: string, offering: Offering): PendingDraft {
  return { ...draft, lines: draft.lines.map(line => line.key === key ? offeringLine(offering, key, line.quantity) : line) };
}
export function switchMode(draft: PendingDraft, split: boolean): PendingDraft {
  const single = split ? draft.single : codes.find(code => (draft.amounts[code] ?? "") !== "") ?? draft.single;
  return { ...draft, split, single };
}
function quantity(value: string): number | null {
  if (!/^[1-9]\d*$/.test(value)) return null;
  const result = Number(value);
  return Number.isSafeInteger(result) && result <= 2147483647 ? result : null;
}
export function draftAllocations(draft: PendingDraft, visitor: boolean): Allocation[] {
  return (visitor ? ["finance"] as Payment[] : draft.split ? codes : [draft.single])
    .filter(code => (draft.amounts[code] ?? "").trim() !== "")
    .map(code => ({ category: code, amount: draft.amounts[code]! }));
}
export function validateDraft(order: OrderDetail, draft: PendingDraft): Record<string, string> {
  const errors: Record<string, string> = {};
  if (order.is_received) errors.order = "Received orders cannot be edited. Reload the latest order.";
  if (!draft.lines.length) errors.items = "Keep at least one item on the order.";
  for (const line of draft.lines) {
    if (quantity(line.quantity) === null) errors[`quantity-${line.key}`] = "Enter a whole quantity from 1 to 2,147,483,647.";
    else {
      const total = (centavos(line.unitPrice) ?? BigInt(0)) * BigInt(quantity(line.quantity)!);
      if (total > BigInt("999999999999")) errors[`quantity-${line.key}`] = "This quantity exceeds the supported line amount.";
    }
  }
  for (const allocation of draftAllocations(draft, order.visitor_id !== null)) {
    const amount = centavos(allocation.amount);
    if (amount === null || amount <= BigInt(0)) errors[`amount-${allocation.category}`] = "Enter a positive amount with at most two decimal places, or leave blank to remove it.";
  }
  if (order.visitor_id !== null && Object.entries(draft.amounts).some(([code, value]) => code !== "finance" && !!value)) {
    errors.allocations = "Visitor allocations must use Finance only.";
  }
  return errors;
}
export function draftTotals(draft: PendingDraft, visitor: boolean): { total: bigint | null; allocated: bigint | null; difference: bigint | null } {
  let total: bigint | null = BigInt(0), allocated: bigint | null = BigInt(0);
  for (const line of draft.lines) {
    const count = quantity(line.quantity), price = centavos(line.unitPrice);
    if (count === null || price === null) { total = null; break; }
    total += price * BigInt(count);
  }
  for (const allocation of draftAllocations(draft, visitor)) {
    const amount = centavos(allocation.amount);
    if (amount === null || amount <= BigInt(0)) { allocated = null; break; }
    allocated += amount;
  }
  return { total, allocated, difference: total === null || allocated === null ? null : total - allocated };
}
export function buildEdit(order: OrderDetail, draft: PendingDraft): PendingEdit {
  if (Object.keys(validateDraft(order, draft)).length) throw new Error("Check the highlighted items and allocation amounts.");
  const quantities = draft.lines.filter(line => line.lineId !== null &&
    Number(line.quantity) !== order.items.find(item => item.id === line.lineId)?.quantity)
    .map(line => ({ line_id: line.lineId!, quantity: Number(line.quantity) }));
  const remove_line_ids = order.items.filter(item => !draft.lines.some(line => line.lineId === item.id)).map(item => item.id);
  const add_items = draft.lines.filter(line => line.lineId === null).map(line => ({ menu_item_id: line.offeringId, quantity: Number(line.quantity) }));
  if ([quantities, remove_line_ids, add_items].some(changes => changes.length > 100)) throw new Error("Save at most 100 changes of each kind per request.");
  return { expected_version: order.version, quantities, remove_line_ids, add_items, allocations: draftAllocations(draft, order.visitor_id !== null) };
}
export async function savePendingEdit(request: RequestApi, order: OrderDetail, draft: PendingDraft): Promise<OrderDetail> {
  await request<OrderResult>(`/api/orders/${order.order_id}`, { method: "PATCH", body: buildEdit(order, draft) });
  return request<OrderDetail>(`/api/orders/${order.order_id}`);
}
