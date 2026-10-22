import { ApiError, type Category, type DateAssignment, type Dish, type Menu, type MenuInput, type RecordedMenu, type RequestApi, type ScheduleResult } from "./api.ts";

export const categoryLabels: Record<Category, string> = { vegetable: "Vegetable", non_vegetable: "Non-vegetable", extra_rice: "Extra Rice" };
// Approved starting values, NOT a claim that these are today's database defaults.
// The current API exposes actual configured prices only on saved menu offerings.
export const referencePrices: Record<Category, string> = { vegetable: "50.00", non_vegetable: "75.00", extra_rice: "15.00" };
export type DishFilters = { q: string; category: Category | ""; active: "" | "true" | "false" };
const collator = new Intl.Collator("en", { sensitivity: "base", numeric: true });
export function alphabetical(dishes: Dish[]): Dish[] {
  return [...dishes].sort((a, b) => collator.compare(a.name, b.name) || a.name.localeCompare(b.name, "en") || a.id - b.id);
}
export async function searchDishes(request: RequestApi, filters: DishFilters, signal?: AbortSignal): Promise<{ dishes: Dish[]; truncated: boolean }> {
  const dishes: Dish[] = [];
  // Bounded catalog reads; refine the search when over 1,000 matches are returned.
  for (let offset = 0; offset < 1000; offset += 100) {
    const query = new URLSearchParams({ q: filters.q.trim(), limit: "100", offset: String(offset) });
    if (filters.category) query.set("category", filters.category);
    if (filters.active) query.set("active", filters.active);
    const page = await request<Dish[]>(`/api/dishes?${query}`, { signal });
    dishes.push(...page);
    if (page.length < 100) return { dishes: alphabetical(dishes), truncated: false };
  }
  return { dishes: alphabetical(dishes), truncated: true };
}
export function selectDish(selected: Dish[], dish: Dish): Dish[] {
  if (!dish.is_active) throw new Error("Inactive dishes cannot be selected for a new menu.");
  if (selected.some(item => item.id === dish.id)) return selected;
  if (selected.length >= 100) throw new Error("A menu supports up to 100 distinct dishes.");
  return [...selected, dish];
}
export async function createDish(request: RequestApi, name: string, category: Category): Promise<Dish> {
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 200 || trimmed.includes("\x00")) throw new Error("Enter a dish name of 1–200 characters.");
  return request<Dish>("/api/dishes", { method: "POST", body: { name: trimmed, category_code: category } });
}
export function menuInput(label: string, selected: Dish[]): MenuInput {
  if (!selected.length || selected.length > 100 || new Set(selected.map(d => d.id)).size !== selected.length) throw new Error("Select between 1 and 100 distinct dishes.");
  if (selected.some(d => !d.is_active)) throw new Error("Only active dishes may be selected.");
  if (label.trim().length > 200 || label.includes("\x00")) throw new Error("Use a menu label of at most 200 characters.");
  return { label: label.trim() || null, dish_ids: selected.map(d => d.id) };
}
export async function createMenu(request: RequestApi, label: string, selected: Dish[], includeDefaultRice = false): Promise<RecordedMenu> {
  return request<RecordedMenu>("/api/menus", { method: "POST", body: { ...menuInput(label, selected), ...(includeDefaultRice ? { include_default_rice: true } : {}) } });
}
export function addDate(dates: string[], day: string): string[] {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== day || day.startsWith("0000")) throw new Error("Select a valid service date.");
  if (dates.includes(day)) return dates;
  if (dates.length >= 366) throw new Error("Assign up to 366 dates per request.");
  return [...dates, day].sort();
}
export type ReviewedDate = DateAssignment & { label: string | null };
export async function inspectDates(request: RequestApi, dates: string[], signal?: AbortSignal): Promise<ReviewedDate[]> {
  if (!dates.length || dates.length > 366 || new Set(dates).size !== dates.length) throw new Error("Select distinct dates before review.");
  const results: ReviewedDate[] = [];
  for (const day of [...dates].sort()) {
    addDate([], day);
    try {
      const menu = await request<Menu>(`/api/menus/by-date/${day}`, { signal });
      results.push({ service_date: day, expected_menu_id: menu.id, label: menu.label });
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) throw error;
      results.push({ service_date: day, expected_menu_id: null, label: null });
    }
  }
  return results;
}
export function needsReplacement(row: ReviewedDate, menuId: number): boolean {
  return row.expected_menu_id !== null && row.expected_menu_id !== menuId;
}
export function scheduleInput(menuId: number, reviewed: ReviewedDate[], confirmed: string[]): { assignments: DateAssignment[] } {
  if (!reviewed.length || reviewed.length > 366 || new Set(reviewed.map(row => row.service_date)).size !== reviewed.length) throw new Error("Review the selected dates first.");
  if (reviewed.some(row => needsReplacement(row, menuId) && !confirmed.includes(row.service_date))) throw new Error("Confirm each existing assignment that will be replaced.");
  return { assignments: reviewed.map(row => ({ service_date: row.service_date, expected_menu_id: row.expected_menu_id })) };
}
export async function assignMenu(request: RequestApi, menuId: number, reviewed: ReviewedDate[], confirmed: string[]): Promise<ScheduleResult> {
  return request<ScheduleResult>(`/api/menus/${menuId}/dates`, { method: "PUT", body: scheduleInput(menuId, reviewed, confirmed) });
}
