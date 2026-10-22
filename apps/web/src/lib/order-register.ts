import { ApiError, type OrderSummary, type RequestApi } from "./api.ts";

export async function loadOrderPage(request: RequestApi, day: string, status: string, offset: number, revision: string | null, signal?: AbortSignal): Promise<{ orders: OrderSummary[]; revision: string }> {
  if (offset > 0 && !revision) throw new Error("Restart the order listing before changing pages.");
  const query = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (day) { query.set("start", day); query.set("end", day); }
  if (status) query.set("status", status);
  if (offset > 0 && revision) query.set("revision", revision);
  return request(`/api/orders/page?${query}`, { signal });
}

export function listingError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) return "The order listing changed. Select Refresh orders to restart from the first page.";
  return error instanceof Error ? error.message : "Unable to load orders.";
}

export function receiveError(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) return "The order's payment allocations do not satisfy the Received requirements. Open Edit Pending and correct them before marking Received.";
  if (error instanceof ApiError && error.status === 409) return "The order changed. Review its refreshed details before trying again.";
  if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) return "The result could not be confirmed. Review the refreshed order before trying again.";
  return error instanceof Error ? error.message : "Unable to confirm the change.";
}
