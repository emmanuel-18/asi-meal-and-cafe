import { ApiError, type Dish, type Menu, type RequestApi } from "./api.ts";

export type DraftDishChange = { original: Dish; updated: Dish | null };

export async function saveDailyMenu(request: RequestApi, day: string, expectedMenuId: number | null, selected: Dish[], changes: DraftDishChange[]): Promise<Menu> {
  return request<Menu>("/api/menus", { method: "POST", body: {
    dish_ids: selected.map(dish => dish.id), include_default_rice: true,
    assignments: [{ service_date: day, expected_menu_id: expectedMenuId }],
    dish_changes: changes.map(({ original, updated }) => ({ id: original.id, expected_name: original.name,
      expected_category: original.category_code, delete: updated === null,
      ...(updated ? { name: updated.name, category_code: updated.category_code } : {}) })),
  } });
}

export function editableMenuDishes(menu: Menu, catalog: Dish[]): Dish[] {
  return menu.items.filter(item => item.category_code !== "extra_rice").flatMap(item => {
    const dish = catalog.find(entry => entry.id === item.dish_id);
    if (!dish) throw new Error("A saved dish was not found in the bounded catalog. Refine or review the catalog before editing this menu.");
    return dish.is_active ? [dish] : [];
  });
}

export async function dailyMenu(request: RequestApi, day: string, signal?: AbortSignal): Promise<Menu | null> {
  try { return await request<Menu>(`/api/menus/by-date/${encodeURIComponent(day)}`, { signal }); }
  catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
}

export async function defaultRicePrice(request: RequestApi, signal?: AbortSignal): Promise<string> {
  const defaults = await request<{ extra_rice_price: string }>("/api/menu-defaults", { signal });
  return defaults.extra_rice_price;
}
