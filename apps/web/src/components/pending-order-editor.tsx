"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type Offering, type OrderDetail, type Payment, type RecordedMenu, type RequestApi } from "@/lib/api";
import { paymentLabels, pesos } from "@/lib/meal";
import { createDraft, draftTotals, offeringLine, replaceLine, savePendingEdit, switchMode, validateDraft } from "@/lib/pending-edit";

export default function PendingOrderEditor({ order, request, onCancel, onSaved, onReload }: {
  order: OrderDetail; request: RequestApi; onCancel: () => void; onSaved: (order: OrderDetail) => Promise<void>; onReload: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(() => createDraft(order));
  const [menu, setMenu] = useState<RecordedMenu | null>(null);
  const [menuLoading, setMenuLoading] = useState(true);
  const [menuError, setMenuError] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [saving, setSaving] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const submitting = useRef(false);
  const nextLine = useRef(1);
  const visitor = order.visitor_id !== null;
  const errors = validateDraft(order, draft);
  const totals = draftTotals(draft, visitor);
  const fieldsDisabled = saving || blocked;
  const offerings = menu?.items.filter(item => `${item.item_name} ${item.category_code.replaceAll("_", " ")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) ?? [];
  const codes = visitor ? ["finance"] as Payment[] : Object.keys(paymentLabels) as Payment[];

  useEffect(() => {
    const controller = new AbortController();
    void request<RecordedMenu>(`/api/menus/${order.menu_id}`, { signal: controller.signal }).then(setMenu).catch(error => {
      if (!(error instanceof Error && error.name === "AbortError")) setMenuError(error instanceof Error ? error.message : "Unable to load recorded menu.");
    }).finally(() => { if (!controller.signal.aborted) setMenuLoading(false); });
    return () => controller.abort();
  }, [order.menu_id, request, reload]);

  function replace(key: string, id: string) {
    const offering = menu?.items.find(item => item.id === Number(id));
    if (offering) setDraft(current => replaceLine(current, key, offering));
  }
  function add(offering: Offering) {
    const key = `new-${nextLine.current++}`;
    setDraft(current => ({ ...current, lines: [...current.lines, offeringLine(offering, key)] }));
    setSelected("");
  }
  function changeQuantity(key: string, value: string) {
    setDraft(current => ({ ...current, lines: current.lines.map(line => line.key === key ? { ...line, quantity: value } : line) }));
  }
  function amount(code: Payment, value: string) {
    setDraft(current => ({ ...current, amounts: { ...current.amounts, [code]: value } }));
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current || blocked || Object.keys(errors).length) return;
    submitting.current = true; setSaving(true); setError("");
    try {
      const refreshed = await savePendingEdit(request, order, draft);
      await onSaved(refreshed);
    } catch (error) {
      const validation = error instanceof ApiError && [400, 422].includes(error.status);
      setBlocked(!validation);
      setError(error instanceof ApiError && error.status === 409 ?
        "This order changed or was marked Received. Your draft was not applied. Reload the latest order and review it before editing again." :
        validation ? "The server rejected these changes. Check the quantities, selected menu items and payment allocations below. You may also reload the latest order." :
        error instanceof ApiError && [401, 403, 404].includes(error.status) ? error.message :
        "The save result could not be confirmed. Reload the latest order before editing again; do not repeat this submission.");
    } finally { submitting.current = false; setSaving(false); }
  }

  return <section className="pending-editor" aria-labelledby="pending-editor-heading">
    <h4 id="pending-editor-heading">Edit Pending order</h4>
    <p className="muted">Customer, service date and recorded menu #{order.menu_id} are fixed. Existing lines keep their recorded prices and categories. Additions and replacements use the server&apos;s recorded-menu offerings.</p>
    {error && <div className="error" role="alert"><p>{error}</p><button type="button" className="secondary" disabled={saving} onClick={() => void onReload()}>Reload latest order</button></div>}
    <form onSubmit={save} noValidate>
      <fieldset className="entry-fields" disabled={fieldsDisabled}><legend className="sr-only">Permitted Pending edits</legend>
        <h4>Items</h4>{errors.items && <p className="field-error" role="alert">{errors.items}</p>}
        <div className="table-scroll" role="region" aria-label="Editable order items" tabIndex={0}><table><caption className="sr-only">Editable order items; prices are read-only</caption>
          <thead><tr><th scope="col">Item and recorded price</th><th scope="col">Quantity</th><th scope="col">Replace / remove</th></tr></thead>
          <tbody>{draft.lines.map((line, index) => <tr key={line.key}><th scope="row">{line.name}<small>{line.category.replaceAll("_", " ")} · {pesos(line.unitPrice)} · {line.lineId === null ? "New snapshot on save" : "Existing snapshot"}</small></th>
            <td><div className="quantity"><button type="button" className="secondary" aria-label={`Decrease item ${index + 1}`} disabled={!/^\d+$/.test(line.quantity) || Number(line.quantity) <= 1}
              onClick={() => changeQuantity(line.key, String(Number(line.quantity) - 1))}>−</button>
              <input type="number" min={1} max={2147483647} step={1} value={line.quantity} aria-label={`Item ${index + 1} quantity`}
                aria-invalid={!!errors[`quantity-${line.key}`]} aria-describedby={errors[`quantity-${line.key}`] ? `error-${line.key}` : undefined}
                onChange={e => changeQuantity(line.key, e.target.value)} />
              <button type="button" className="secondary" aria-label={`Increase item ${index + 1}`} disabled={!/^\d+$/.test(line.quantity) || Number(line.quantity) >= 2147483647}
                onClick={() => changeQuantity(line.key, String(Number(line.quantity) + 1))}>+</button></div>
              {errors[`quantity-${line.key}`] && <p className="field-error" id={`error-${line.key}`}>{errors[`quantity-${line.key}`]}</p>}</td>
            <td><div className="edit-line-actions"><select value="" aria-label={`Replace item ${index + 1}`} disabled={!menu || menuLoading} onChange={e => replace(line.key, e.target.value)}>
              <option value="">Replace with offering…</option>{offerings.map(item => <option key={item.id} value={item.id}>{item.item_name} · {pesos(item.unit_price)}</option>)}</select>
              <button type="button" className="secondary" disabled={draft.lines.length <= 1} onClick={() => setDraft(current => ({ ...current, lines: current.lines.filter(i => i.key !== line.key) }))}
                aria-label={`Remove item ${index + 1}`}>Remove</button></div></td></tr>)}</tbody></table></div>
        <div className="offering-picker">
          {menuLoading && <p role="status">Loading recorded menu…</p>}
          {menuError && <p className="error" role="alert">{menuError} <button type="button" className="text-button" onClick={() => { setMenuError(""); setMenuLoading(true); setReload(current => current + 1); }}>Retry menu lookup</button></p>}
          <label>Search recorded-menu offerings<input value={query} maxLength={100} onChange={e => { setQuery(e.target.value); setSelected(""); }} disabled={!menu} /></label>
          <div className="inline-form"><label className="grow">Offering to add<select value={selected} disabled={!menu || menuLoading} onChange={e => setSelected(e.target.value)}>
            <option value="">Select an offering</option>{offerings.map(item => <option key={item.id} value={item.id}>{item.item_name} · {pesos(item.unit_price)}</option>)}</select></label>
            <button type="button" className="secondary" disabled={!selected || menuLoading} onClick={() => { const offering = menu?.items.find(i => i.id === Number(selected)); if (offering) add(offering); }}>Add item</button></div>
          {menu && !offerings.length && <p className="muted">No recorded-menu offerings match this search.</p>}
        </div>
        <h4>Payment allocations</h4>
        {!visitor && <label className="check-label payment-choice"><input type="checkbox" checked={draft.split} onChange={e => setDraft(current => switchMode(current, e.target.checked))} />Split payment</label>}
        {visitor ? <p>Visitor orders use Finance only.</p> : !draft.split && <label>Payment category<select value={draft.single} onChange={e => setDraft(current => ({ ...current, single: e.target.value as Payment,
          amounts: { [e.target.value]: current.amounts[current.single] ?? "" } }))}>{codes.map(code => <option key={code} value={code}>{paymentLabels[code]}</option>)}</select></label>}
        {visitor ? <p className="muted">Finance is automatically set to the item total when saved.</p> : <p className="muted">Leave an amount blank to remove that allocation. Switching to a single method saves only its displayed category and amount. Pending allocations may be incomplete.</p>}
        {!visitor && <div className="allocation-grid">{(draft.split ? codes : [draft.single]).map(code => <label key={code}>{paymentLabels[code]} amount
          <input inputMode="decimal" type="text" maxLength={13} value={draft.amounts[code] ?? ""} placeholder="0.00"
            aria-invalid={!!errors[`amount-${code}`]} aria-describedby={errors[`amount-${code}`] ? `error-amount-${code}` : undefined} onChange={e => amount(code, e.target.value)} />
          {errors[`amount-${code}`] && <span className="field-error" id={`error-amount-${code}`}>{errors[`amount-${code}`]}</span>}</label>)}</div>}
        {errors.allocations && <p className="field-error" role="alert">{errors.allocations}</p>}
        <div className="allocation-summary" aria-live="polite"><span>Item total <strong>{totals.total === null ? "Check quantities" : pesos(totals.total)}</strong></span>
          <span>Allocated <strong>{totals.allocated === null ? "Check amounts" : pesos(totals.allocated)}</strong></span>
          <span>Difference <strong>{totals.difference === null ? "—" : pesos(totals.difference)}</strong></span></div>
      </fieldset>
      <div className="button-row"><button type="submit" disabled={fieldsDisabled || !!Object.keys(errors).length}>{saving ? "Saving…" : "Save Pending changes"}</button>
        <button type="button" className="secondary" disabled={saving} onClick={onCancel}>Cancel</button></div>
    </form>
  </section>;
}
