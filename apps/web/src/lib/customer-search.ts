import type { Employee, RequestApi, Visitor } from "./api.ts";

export type Customer = { employee_number: string; name: string } | { visitor_id: number; name: string };
export type CustomerResult = { customer: Customer; detail: string };

export function suggestionKey(key: string, active: number, count: number, open: boolean): { action: "move" | "select" | "close" | "none"; index: number } {
  if (key === "ArrowDown" && count) return { action: "move", index: Math.min(active + 1, count - 1) };
  if (key === "ArrowUp" && count) return { action: "move", index: active < 0 ? count - 1 : Math.max(active - 1, 0) };
  if (key === "Enter" && open && active >= 0 && active < count) return { action: "select", index: active };
  if (key === "Escape" || key === "Tab") return { action: "close", index: -1 };
  return { action: "none", index: active };
}

// Cancellation also suppresses responses from transports that ignore AbortSignal.
export function scheduleCustomerSearch(kind: "employee" | "visitor", term: string, request: RequestApi,
  onSuccess: (results: CustomerResult[]) => void, onError: (error: unknown) => void, onDone: () => void): () => void {
  const controller = new AbortController();
  let active = true;
  if (!term.trim()) return () => { active = false; controller.abort(); };
  const timer = setTimeout(async () => {
    try {
      const path = `/api/${kind === "employee" ? "employees" : "visitors"}?q=${encodeURIComponent(term.trim())}&limit=20`;
      const results: CustomerResult[] = kind === "employee" ? (await request<Employee[]>(path, { signal: controller.signal })).map(row => ({
        customer: { employee_number: row.employee_number, name: row.full_name }, detail: row.employee_number,
      })) : (await request<Visitor[]>(path, { signal: controller.signal })).map(row => ({
        customer: { visitor_id: row.id, name: row.display_name }, detail: `Visitor #${row.id}`,
      }));
      if (active) onSuccess(results.slice(0, 20));
    } catch (error) { if (active) onError(error); }
    finally { if (active) onDone(); }
  }, 275);
  return () => { active = false; clearTimeout(timer); controller.abort(); };
}
