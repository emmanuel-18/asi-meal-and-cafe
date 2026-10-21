"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type Category, type Dish, type RequestApi } from "@/lib/api";
import { categoryLabels, createDish, searchDishes, type DishFilters } from "@/lib/menus";

export default function DishCatalog({ request, selected, onSelect, disabled, onBusy }: {
  request: RequestApi; selected: Dish[]; onSelect: (dish: Dish) => void; disabled: boolean; onBusy: (busy: boolean) => void;
}) {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [active, setActive] = useState<DishFilters["active"]>("");
  const [filters, setFilters] = useState<DishFilters>({ q: "", category: "", active: "" });
  const [rows, setRows] = useState<Dish[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [name, setName] = useState("");
  const [newCategory, setNewCategory] = useState<Category>("vegetable");
  const submitting = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    void searchDishes(request, filters, controller.signal).then(result => { setRows(result.dishes); setTruncated(result.truncated); }).catch(error => {
      if (!(error instanceof Error && error.name === "AbortError")) { setRows([]); setError(error instanceof Error ? error.message : "Unable to search dishes."); }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [request, filters]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current || blocked || disabled || selected.length >= 100) return;
    submitting.current = true; setCreating(true); onBusy(true); setError(""); setNotice("");
    try {
      const dish = await createDish(request, name, newCategory);
      onSelect(dish); setName(""); setNotice(`${dish.name} created and selected for the new menu.`);
      setLoading(true); setPage(0); setFilters(current => ({ ...current }));
    } catch (error) {
      const uncertain = error instanceof ApiError && (error.status === 0 || error.status >= 500);
      setBlocked(uncertain);
      setError(uncertain ? "The creation result could not be confirmed. Search the catalog before starting another dish; no automatic retry was sent." : error instanceof Error ? error.message : "Unable to create dish.");
    } finally { submitting.current = false; setCreating(false); onBusy(false); }
  }

  return <section className="panel"><h3>Dish catalog</h3>
    <p className="muted">Alphabetical matches. Menu-selection counts are not exposed by the API; sales volume is not used for ordering.</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <form className="filter-row" onSubmit={e => { e.preventDefault(); setError(""); setLoading(true); setPage(0); setFilters({ q, category, active }); }}>
      <label className="grow">Dish name<input maxLength={100} value={q} onChange={e => setQ(e.target.value)} /></label>
      <label>Category<select value={category} onChange={e => setCategory(e.target.value as Category | "")}><option value="">All categories</option>
        {Object.entries(categoryLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
      <label>Active status<select value={active} onChange={e => setActive(e.target.value as DishFilters["active"])}><option value="">All statuses</option><option value="true">Active</option><option value="false">Inactive</option></select></label>
      <button type="submit" disabled={loading}>Search</button>
    </form>
    {loading ? <p role="status">Loading dishes…</p> : !rows.length ? <p role="status" className="muted">No dishes match these filters.</p> : <>
      {truncated && <p className="notice">The first 1,000 matches are shown alphabetically. Refine your search to find other dishes.</p>}
      <div className="table-scroll" role="region" aria-label="Dish catalog search results" tabIndex={0}><table><caption className="sr-only">Dish catalog search results</caption><thead><tr><th scope="col">Dish</th><th scope="col">Category</th><th scope="col">Status</th><th scope="col">Select</th></tr></thead>
        <tbody>{rows.slice(page * 20, page * 20 + 20).map(dish => {
          const picked = selected.some(item => item.id === dish.id);
          return <tr key={dish.id}><th scope="row">{dish.name}<small>Dish #{dish.id}</small></th><td>{categoryLabels[dish.category_code]}</td><td>{dish.is_active ? "Active" : "Inactive"}</td>
            <td><button type="button" className="secondary" disabled={disabled || creating || !dish.is_active || picked || selected.length >= 100}
              onClick={() => onSelect(dish)} aria-label={`Select ${dish.name}`}>{picked ? "Selected" : "Select"}</button></td></tr>;
        })}</tbody></table></div>
      <div className="pagination"><button type="button" className="secondary" disabled={!page} onClick={() => setPage(current => current - 1)}>Previous dishes</button><span>Page {page + 1}</span>
        <button type="button" className="secondary" disabled={(page + 1) * 20 >= rows.length} onClick={() => setPage(current => current + 1)}>Next dishes</button></div>
    </>}
    <details className="new-dish"><summary>Create a reusable dish</summary>
      <p className="muted">Search first to avoid accidental duplicates. No category reclassification, deletion, or price overrides are available.</p>
      <form onSubmit={create} className="inline-form"><label className="grow">New dish name<input value={name} required maxLength={200} onChange={e => setName(e.target.value)} disabled={creating || disabled || blocked} /></label>
        <label>New dish category<select value={newCategory} onChange={e => setNewCategory(e.target.value as Category)} disabled={creating || disabled || blocked}>
          {Object.entries(categoryLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
        <button type="submit" disabled={creating || disabled || blocked || !name.trim() || selected.length >= 100}>{creating ? "Creating…" : "Create and select dish"}</button></form>
      {blocked && <button type="button" className="secondary" onClick={() => { setName(""); setBlocked(false); setNotice("Review the catalog before entering another dish."); }}>Start another dish after checking catalog</button>}
    </details>
  </section>;
}
