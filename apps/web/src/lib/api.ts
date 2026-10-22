// Matches the existing FastAPI schemas. Cookies stay HttpOnly; CSRF stays in memory.
export type Role = "admin" | "assistant_admin" | "super_admin";
export type Session = { user: { id: number; login_name: string; display_name: string; role: Role; password_change_required: boolean }; csrf_token: string };
export type Employee = { employee_number: string; full_name: string; position: string | null; campaign: string | null; line_of_business: string | null };
export type Visitor = { id: number; display_name: string };
export type Category = "vegetable" | "non_vegetable" | "extra_rice";
export type Dish = { id: number; name: string; category_code: Category; is_active: boolean };
export type MenuInput = { label: string | null; dish_ids: number[] };
export type DateAssignment = { service_date: string; expected_menu_id: number | null };
export type ScheduleResult = { menu_id: number; service_dates: string[] };
export type Payment = "cash" | "gcash" | "sd" | "incentive" | "finance";
export type Offering = { id: number; dish_id: number; item_name: string; category_code: Category; unit_price: string };
export type Menu = { id: number; service_date: string; label: string | null; items: Offering[] };
export type RecordedMenu = Omit<Menu, "service_date">;
export type Allocation = { category: Payment; amount: string };
export type OrderInput = {
  request_key: string; service_date: string; menu_id: number;
  employee_number?: string; visitor_id?: number;
  items: { menu_item_id: number; quantity: number }[]; allocations: Allocation[];
};
export type OrderResult = { order_id: number; version: number; is_received: boolean; total: string };
export type OrderSummary = OrderResult & { service_date: string; menu_id: number; employee_number: string | null; visitor_id: number | null; customer_name: string };
export type OrderDetail = Omit<OrderSummary, "total"> & {
  position: string | null; campaign: string | null; line_of_business: string | null;
  items: { id: number; line_number: number; source_menu_item_id: number; name: string; category: Category; unit_price: string; quantity: number; line_total: string }[];
  allocations: (Allocation & { id: number })[];
};
export type PendingEdit = {
  expected_version: number; quantities: { line_id: number; quantity: number }[];
  remove_line_ids: number[]; add_items: { menu_item_id: number; quantity: number }[]; allocations: Allocation[];
};
export type ApiOptions = { method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE"; body?: unknown; signal?: AbortSignal; csv?: Blob };
export type RequestApi = <T>(path: string, options?: ApiOptions) => Promise<T>;

export class ApiError extends Error {
  status: number;
  constructor(status: number, safeDetail?: string) {
    super(safeDetail ?? (status === 401 ? "Your session has expired. Please sign in again." :
      status === 403 ? "This action is not permitted. Refresh your session and try again." :
      status === 404 ? "The requested record or menu was not found." :
      status === 409 ? "This record changed. Review the refreshed details before trying again." :
      status === 422 || status === 400 ? "Check the entered details. The request was not accepted." :
      status === 429 ? "Too many attempts. Please wait a minute and try again." :
      "The service is unavailable. Please try again."));
    this.status = status;
  }
}

export async function apiRequest<T>(path: string, options: ApiOptions = {}, csrf?: string): Promise<T> {
  if (!/^\/(auth|api)\//.test(path)) throw new Error("Invalid API path");
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = options.csv ? "text/csv" : "application/json";
    if (csrf) headers["X-CSRF-Token"] = csrf;
    if (path === "/auth/login") headers["X-ASI-Request"] = "1";
  }
  let response: Response;
  try {
    response = await fetch(path, { method, headers, credentials: "same-origin", cache: "no-store",
      body: options.csv ?? (options.body === undefined ? undefined : JSON.stringify(options.body)), signal: options.signal });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(0);
  }
  if (!response.ok && !(path === "/api/employees/import" && options.csv && response.status === 422)) {
    const safeConflicts = ["Visitor changed; refresh before trying again", "Visitor is used by an order and cannot be deleted",
      "Dish changed; refresh before trying again", "Dish is used by a saved menu and cannot be deleted"];
    let detail: string | undefined;
    if (response.status === 409 && /^\/api\/(visitors|dishes)\/\d+$/.test(path)) {
      try { const body = await response.json(); if (safeConflicts.includes(body?.detail)) detail = body.detail; } catch { /* Do not expose arbitrary response data. */ }
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  try {
    const result = await response.json();
    if (!response.ok && (result?.status !== "failed" || !Number.isSafeInteger(result?.import_id))) throw new ApiError(response.status);
    return result as T;
  } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(response.ok ? 0 : response.status); }
}
