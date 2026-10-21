"use client";

import { useRef, useState } from "react";
import { ApiError, type Dish, type Menu, type RecordedMenu, type RequestApi } from "@/lib/api";
import { categoryLabels, createMenu, referencePrices, selectDish } from "@/lib/menus";
import { pesos } from "@/lib/meal";
import DishCatalog from "./dish-catalog";
import MenuScheduling from "./menu-scheduling";

export default function MenuWorkspace({ request }: { request: RequestApi }) {
  const [selected, setSelected] = useState<Dish[]>([]);
  const [label, setLabel] = useState("");
  const [menu, setMenu] = useState<RecordedMenu | null>(null);
  const [menuId, setMenuId] = useState("");
  const [inspectDate, setInspectDate] = useState("");
  const [inspectedDate, setInspectedDate] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [dishBusy, setDishBusy] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const submitting = useRef(false);

  function choose(dish: Dish) {
    setSelected(current => current.some(item => item.id === dish.id) || current.length >= 100 ? current : selectDish(current, dish));
    setDraftSaved(false);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current || blocked || draftSaved || dishBusy) return;
    submitting.current = true; setCreating(true); setError(""); setNotice("");
    try {
      const saved = await createMenu(request, label, selected);
      setMenu(saved); setMenuId(String(saved.id)); setInspectedDate(null); setDraftSaved(true);
      setNotice(`Menu #${saved.id} created. Review its actual backend-configured prices below, then choose service dates.`);
    } catch (error) {
      const uncertain = error instanceof ApiError && (error.status === 0 || error.status >= 500);
      setBlocked(uncertain);
      setError(uncertain ? "The menu creation result could not be confirmed. No automatic retry was sent. The API has no menu index or creation request key; confirm the outcome before starting another definition." :
        error instanceof ApiError && error.status === 409 ? "A selected dish may have changed or become inactive. Search the catalog again, remove any outdated selection and review the new definition before saving." :
        error instanceof Error ? error.message : "Unable to save menu.");
    } finally { submitting.current = false; setCreating(false); }
  }
  async function inspect(byDate: boolean, event: React.FormEvent) {
    event.preventDefault(); if (submitting.current) return;
    if (!byDate && (!/^[1-9]\d*$/.test(menuId) || !Number.isSafeInteger(Number(menuId)))) { setError("Enter a valid menu ID."); return; }
    submitting.current = true; setInspecting(true); setError(""); setNotice(""); setMenu(null); setInspectedDate(null);
    try {
      const saved = await request<RecordedMenu | Menu>(byDate ? `/api/menus/by-date/${inspectDate}` : `/api/menus/${menuId}`);
      setMenu(saved); setMenuId(String(saved.id)); setInspectedDate(byDate ? inspectDate : null);
    } catch (error) {
      setError(error instanceof ApiError && error.status === 404 ? byDate ? "No menu is assigned to this service date." : "No menu exists with this ID." : error instanceof Error ? error.message : "Unable to inspect menu.");
    } finally { submitting.current = false; setInspecting(false); }
  }

  return <>
    <div className="section-heading"><h2>Menu and dish management</h2></div>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <DishCatalog request={request} selected={selected} onSelect={choose} disabled={creating || inspecting || blocked} onBusy={setDishBusy} />
    <section className="panel"><h3>Review new menu</h3>
      <p className="muted">Each save creates a new reusable definition. Existing menus and their assigned dates are unchanged until an explicit date assignment.</p>
      <form onSubmit={save}><fieldset className="entry-fields" disabled={creating || inspecting || dishBusy || blocked}><legend className="sr-only">New menu definition</legend>
        <label>Menu label (optional)<input value={label} maxLength={200} onChange={e => { setLabel(e.target.value); setDraftSaved(false); }} /></label>
        <p>{selected.length} / 100 dishes selected.</p>
        {!selected.length ? <p className="muted">Select dishes above, or create and select a reusable dish.</p> : <div className="table-scroll" role="region" aria-label="Selected dishes" tabIndex={0}><table><caption className="sr-only">Review selected dishes before saving</caption>
          <thead><tr><th scope="col">Dish</th><th scope="col">Catalog category</th><th scope="col">Reference price</th><th scope="col">Action</th></tr></thead>
          <tbody>{selected.map(dish => <tr key={dish.id}><th scope="row">{dish.name}</th><td>{categoryLabels[dish.category_code]}</td><td>{pesos(referencePrices[dish.category_code])}</td>
            <td><button type="button" className="secondary" onClick={() => { setSelected(current => current.filter(item => item.id !== dish.id)); setDraftSaved(false); }} aria-label={`Remove selected ${dish.name}`}>Remove</button></td></tr>)}</tbody></table></div>}
        <p className="notice">Reference prices are the approved starting values: Vegetable ₱50, Non-vegetable ₱75, Extra Rice ₱15. The API does not expose current category defaults before saving. The server determines actual menu categories and prices; inspect the saved values before assigning dates.</p>
        <button type="submit" disabled={creating || inspecting || dishBusy || blocked || draftSaved || !selected.length}>{creating ? "Saving…" : draftSaved ? "New menu saved" : "Save new menu"}</button>
      </fieldset></form>
      <button type="button" className="text-button" disabled={creating || inspecting || dishBusy} onClick={() => { setSelected([]); setLabel(""); setDraftSaved(false); setBlocked(false); setError(""); }}>Start a separate new definition</button>
    </section>
    <section className="panel"><h3>Inspect an existing menu</h3>
      <div className="menu-inspection"><form className="inline-form" onSubmit={e => void inspect(false, e)}><label className="grow">Saved menu ID<input inputMode="numeric" value={menuId} onChange={e => setMenuId(e.target.value)} required maxLength={19} disabled={creating || inspecting} /></label>
        <button type="submit" className="secondary" disabled={creating || inspecting || !menuId}>Load menu</button></form>
        <form className="inline-form" onSubmit={e => void inspect(true, e)}><label className="grow">Inspect service date<input type="date" value={inspectDate} onChange={e => setInspectDate(e.target.value)} required disabled={creating || inspecting} /></label>
          <button type="submit" className="secondary" disabled={creating || inspecting || !inspectDate}>Inspect date</button></form></div>
      <p className="muted">Menus can be loaded by ID or assigned date; the current API has no menu index.</p>
      {inspecting && <p role="status">Loading saved menu…</p>}
      {menu && <div className="saved-menu"><h4>Saved menu #{menu.id}{menu.label ? ` · ${menu.label}` : ""}</h4>{inspectedDate && <p>Currently assigned to {inspectedDate}.</p>}
        {!menu.items.length ? <p className="muted">This saved menu has no offerings.</p> : <div className="table-scroll" role="region" aria-label="Saved menu offerings" tabIndex={0}><table><caption>Actual saved offerings from the backend</caption>
          <thead><tr><th scope="col">Offering</th><th scope="col">Configured category</th><th scope="col">Configured price</th></tr></thead>
          <tbody>{menu.items.map(item => <tr key={item.id}><th scope="row">{item.item_name}</th><td>{categoryLabels[item.category_code]}</td><td>{pesos(item.unit_price)}</td></tr>)}</tbody></table></div>}
        <p className="muted">To change offerings, select dishes for a separate new definition above, save it, then reassign only the intended dates. Saved offerings are read-only here.</p>
      </div>}
    </section>
    {menu && <MenuScheduling key={menu.id} menu={menu} request={request} />}
  </>;
}
