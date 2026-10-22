"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type Dish, type Menu, type RequestApi } from "@/lib/api";
import { dailyMenu, defaultRicePrice, editableMenuDishes, saveDailyMenu, type DraftDishChange } from "@/lib/daily-menu";
import { categoryLabels, searchDishes, selectDish } from "@/lib/menus";
import { operationalToday, pesos } from "@/lib/meal";
import DishCatalog from "./dish-catalog";
import MenuScheduling from "./menu-scheduling";

export default function MenuWorkspace({ request, initialDate, onSaved }: { request: RequestApi; initialDate?: string; onSaved?: () => void }) {
  const [day, setDay] = useState(initialDate || operationalToday);
  const [snapshot, setSnapshot] = useState<{ day: string; menu: Menu | null } | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<Dish[]>([]);
  const [ricePrice, setRicePrice] = useState<string | null>(null);
  const [changes, setChanges] = useState<DraftDishChange[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dishBusy, setDishBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const operation = useRef(false);
  const lookupSequence = useRef(0);
  const current = snapshot?.day === day ? snapshot.menu : undefined;

  useEffect(() => {
    const controller = new AbortController();
    const sequence = ++lookupSequence.current;
    void dailyMenu(request, day, controller.signal).then(menu => {
      if (!controller.signal.aborted && sequence === lookupSequence.current) {
        setSnapshot({ day, menu });
      }
    }).catch(error => {
      if (!controller.signal.aborted && sequence === lookupSequence.current) setError(error instanceof Error ? error.message : "Unable to load the menu.");
    }).finally(() => { if (!controller.signal.aborted && sequence === lookupSequence.current) setLoading(false); });
    return () => controller.abort();
  }, [day, revision, request]);

  async function begin() {
    if (operation.current || current === undefined) return;
    operation.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const catalog = current ? await searchDishes(request, { q: "", category: "", active: "" }) : null;
      const original = current && catalog ? editableMenuDishes(current, catalog.dishes) : [];
      const price = await defaultRicePrice(request);
      setRicePrice(price); setSelected(original); setChanges([]); setEditing(true); setConfirmed(false);
    } catch (error) { setError(error instanceof Error ? error.message : "Unable to check Extra Rice. Retry before editing."); }
    finally { operation.current = false; setBusy(false); }
  }
  function choose(dish: Dish) {
    setSelected(items => items.some(item => item.id === dish.id) ? items.filter(item => item.id !== dish.id) : selectDish(items, dish));
    setConfirmed(false);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (operation.current || blocked || dishBusy || current === undefined || (current && !confirmed)) return;
    operation.current = true; setBusy(true); setError(""); setNotice("");
    try {
      await saveDailyMenu(request, day, current?.id ?? null, selected, changes);
      setChanges([]); setEditing(false); onSaved?.();
      try { setSnapshot({ day, menu: await dailyMenu(request, day) }); setNotice("Menu saved and available for Orders."); }
      catch { setError("The menu was assigned, but the current menu could not be refreshed. Use Refresh to review it."); }
    } catch (error) {
      if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
        setBlocked(true); setError("The save could not be confirmed. Refresh and review the saved menu and catalog before trying again.");
      } else setError(error instanceof Error ? error.message : "Unable to save the menu.");
    }
    finally { operation.current = false; setBusy(false); }
  }
  function refresh() { setLoading(true); setError(""); setConfirmed(false); setRevision(value => value + 1); }

  return <div className="daily-menu-workspace">
    <div className="section-heading"><div><h2>Today’s menu</h2><p className="muted">Review meals available for the selected service date.</p></div></div>
    <section className="panel"><div className="inline-form"><label>Service date<input type="date" value={day} required disabled={busy || dishBusy || blocked}
      onChange={e => { if (editing && !window.confirm("Changing date discards unsaved menu selections. Continue?")) return;
        setDay(e.target.value); setLoading(true); setEditing(false); setSelected([]); setConfirmed(false); setError(""); setNotice(""); }} /></label>
      <button type="button" className="secondary" disabled={busy || !day} onClick={refresh}>Refresh menu</button>
      <button type="button" disabled={busy || loading || current === undefined || editing || blocked} onClick={() => void begin()}>Add meals</button></div>
      {loading && <p role="status">Loading menu…</p>}
      {error && <p className="error" role="alert">{error} {(!busy && !blocked) && <button type="button" className="text-button" onClick={refresh}>Refresh and review</button>}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {snapshot?.day === day && <div className="daily-menu-summary"><h3>Saved meals available</h3>{snapshot.menu ? <>
        {(["vegetable", "non_vegetable", "extra_rice"] as const).map(category => <div key={category}><h4>{categoryLabels[category]}</h4>
          {snapshot.menu!.items.filter(item => item.category_code === category).length ? <ul>{snapshot.menu!.items.filter(item => item.category_code === category).map(item =>
            <li key={item.id}>{item.item_name} · {pesos(item.unit_price)}</li>)}</ul> : <p className="muted">None scheduled.</p>}</div>)}
        </> : <p>No meals have been scheduled for this date. Choose Add meals to prepare a menu.</p>}</div>}
      {snapshot && snapshot.day !== day && error && <p className="muted">The last reliably loaded menu was for {snapshot.day}; refresh the selected date before editing.</p>}
    </section>
    {editing && <><div className="daily-menu-columns"><DishCatalog request={request} selected={selected} changes={changes} onSelect={choose} onCatalogChange={(original, dish) => { setChanges(items => [...items.filter(item => item.original.id !== original.id), { original, updated: dish }]); setSelected(items => items.flatMap(item => item.id === original.id ? dish ? [dish] : [] : [item])); setConfirmed(false); }} disabled={busy || blocked} onBusy={setDishBusy} />
      <section className="panel"><h3>Selected meals · unsaved</h3><p>{selected.length} / 99 selected</p>
        {current && <p className="muted">Selections use active catalog dishes and current configured prices. Inactive dishes are excluded from this draft. Historical orders remain unchanged.</p>}
        <p>Extra Rice - {ricePrice === null ? "Price unavailable" : pesos(ricePrice)} - Always included</p>
        {current?.items.some(item => item.category_code === "extra_rice") && <p className="muted">The new menu will include one default Extra Rice offering. The saved menu remains unchanged.</p>}
        <ul className="daily-selection">{selected.map(dish => <li key={dish.id}><span>{dish.name} · {categoryLabels[dish.category_code]}{!dish.is_active ? " · Inactive; remove before saving" : ""}</span>
          {<button type="button" className="secondary" disabled={busy || blocked} onClick={() => choose(dish)}>Unselect</button>}</li>)}</ul>
        <p className="muted">Draft changes do not affect Orders. The current Extra Rice price is applied when saved.</p>
        <form onSubmit={save}>{current && <label className="check-label"><input type="checkbox" checked={confirmed} disabled={busy || loading} onChange={e => setConfirmed(e.target.checked)} />Confirm replacement of the saved menu for {day}.</label>}
          <button type="submit" disabled={busy || loading || dishBusy || blocked || selected.length > 99 || selected.some(dish => !dish.is_active) || current === undefined || (!!current && !confirmed)}>{busy ? "Saving…" : "Save menu"}</button></form>
        {!blocked && <button type="button" className="text-button" disabled={busy || dishBusy} onClick={() => { setEditing(false); setSelected([]); setChanges([]); setNotice(""); }}>Discard draft</button>}
      </section></div></>}
    {snapshot?.day === day && snapshot.menu && <details><summary>Schedule this saved menu for more dates</summary><MenuScheduling key={snapshot.menu.id} menu={snapshot.menu} request={request} /></details>}
  </div>;
}
