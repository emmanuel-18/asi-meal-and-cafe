"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type Allocation, type Menu, type OrderInput, type OrderResult, type Payment, type RequestApi } from "@/lib/api";
import { allocationTotal, buildOrder, decimal, itemTotal, operationalToday, paymentLabels, pesos } from "@/lib/meal";
import CustomerPicker, { type Customer } from "./customer-picker";

export default function OrderEntry({ request, onSaved, onConfigureMenu, menuRevision }: { request: RequestApi; onSaved: (id: number) => void; onConfigureMenu: (day: string) => void; menuRevision: number }) {
  const [day, setDay] = useState(operationalToday);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [kind, setKind] = useState<"employee" | "visitor">("employee");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [split, setSplit] = useState(false);
  const [payment, setPayment] = useState<Payment>("cash");
  const [amounts, setAmounts] = useState<Partial<Record<Payment, string>>>({});
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState<OrderInput | null>(null);
  const submitted = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const menuRef = useRef<Menu | null>(null);
  const selectedRef = useRef(false);
  const previousMenuRevision = useRef(menuRevision);
  useEffect(() => { selectedRef.current = Object.values(quantities).some(value => value > 0); menuRef.current = menu; }, [quantities, menu]);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (previousMenuRevision.current !== menuRevision) {
      previousMenuRevision.current = menuRevision;
      if (selectedRef.current) return;
    }
    const current = new AbortController(); controller.current?.abort(); controller.current = current;
    void request<Menu>(`/api/menus/by-date/${encodeURIComponent(day)}`, { signal: current.signal }).then(loaded => {
      if (!current.signal.aborted) { if (menuRef.current && menuRef.current.id !== loaded.id) setQuantities({}); setMenu(loaded); setError(""); }
    }).catch(error => {
      if (!current.signal.aborted) { setMenu(null); setQuantities({}); setError(error instanceof ApiError && error.status === 404 ?
        "No menu is scheduled for this date. Save the daily menu first." : error instanceof Error ? error.message : "Unable to load menu."); }
    }).finally(() => { if (!current.signal.aborted) setLoading(false); });
    return () => current.abort();
  }, [day, revision, request, menuRevision]);
  const total = menu ? itemTotal(menu, quantities) : BigInt(0);
  const categories = Object.keys(paymentLabels) as Payment[];
  const allocations: Allocation[] = kind === "visitor" ? [{ category: "finance", amount: decimal(total) }] : split ?
    categories.filter(code => (amounts[code] ?? "").trim() !== "").map(code => ({ category: code, amount: amounts[code]! })) :
    [{ category: payment, amount: decimal(total) }];
  const allocated = allocationTotal(allocations);

  function loadMenu(event: React.FormEvent) {
    event.preventDefault();
    if (selectedRef.current && !window.confirm("Refreshing may replace the menu and clear selected quantities. Continue?")) return;
    setLoading(true); setError(""); setRevision(value => value + 1);
  }

  async function save() {
    if (submitted.current) return;
    submitted.current = true; setSaving(true); setError("");
    try {
      if (!menu || !customer) throw new Error("Select an assigned menu and a customer.");
      const identity = "employee_number" in customer ? { employee_number: customer.employee_number } : { visitor_id: customer.visitor_id };
      const body = retry ?? buildOrder(crypto.randomUUID(), menu, quantities, identity, allocations);
      // Retain the exact key and payload if the network outcome is uncertain.
      setRetry(body);
      try {
        const result = await request<OrderResult>("/api/orders", { method: "POST", body });
        onSaved(result.order_id);
      } catch (error) {
        if (error instanceof ApiError && [400, 403, 404, 409, 422].includes(error.status)) setRetry(null);
        throw error;
      }
    } catch (error) { setError(error instanceof Error ? error.message : "Unable to create order."); }
    finally { submitted.current = false; setSaving(false); }
  }

  function quantity(id: number, value: number) {
    setQuantities(current => ({ ...current, [id]: Math.max(0, Math.min(2147483647, Math.trunc(value) || 0)) }));
  }

  return <div className="order-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    {retry && !saving && <p className="notice" role="status">The result could not be confirmed. Retry the same order below; its request key prevents duplicate processing. Check the order list before starting another order.</p>}
    <div className="order-layout"><div className="order-main"><fieldset disabled={saving || !!retry} className="entry-fields"><legend className="sr-only">New order details</legend>
      <section className="panel service-panel"><h3><span className="step-number">1</span> Service date</h3><form onSubmit={loadMenu} className="inline-form">
        <label>Menu service date<input type="date" required value={day} onChange={e => {
          if (selectedRef.current && !window.confirm("Changing date clears selected menu items. Continue?")) return;
          controller.current?.abort(); setLoading(true); setDay(e.target.value); setMenu(null); setQuantities({}); setError("");
        }} /></label><button type="submit" disabled={loading}>{loading ? "Loading menu…" : "Refresh menu"}</button>
      </form>{menu && <p className="muted">{menu.label || "Saved menu"} · {menu.service_date}</p>}
        {!loading && !menu && <button type="button" className="secondary" onClick={() => onConfigureMenu(day)}>Set up menu for this date</button>}</section>
      <section className="panel customer-panel"><h3><span className="step-number">2</span> Customer</h3><fieldset className="choice-row"><legend>Customer type</legend>
        {(["employee", "visitor"] as const).map(value => <label key={value}><input type="radio" name="customer-kind" checked={kind === value}
          onChange={() => { setKind(value); setCustomer(null); setSplit(false); setAmounts({}); }} />{value === "employee" ? "Employee" : "Visitor"}</label>)}
      </fieldset>
      <CustomerPicker key={kind} kind={kind} request={request} selected={customer} onSelect={setCustomer} /></section>
      <section className="panel items-panel"><h3><span className="step-number">3</span> Menu items</h3>{!menu ? <p className="muted">Load an assigned menu to select items.</p> : !menu.items.length ?
        <p className="muted">This menu has no offerings. Ask staff to configure it.</p> : <div className="table-scroll" role="region" aria-label="Menu offerings and quantities" tabIndex={0}><table><caption className="sr-only">Menu offerings and quantities</caption>
          <thead><tr><th scope="col">Dish</th><th scope="col" className="numeric">Unit price</th><th scope="col">Quantity</th><th scope="col" className="numeric">Line total</th></tr></thead>
          <tbody>{menu.items.map(item => <tr key={item.id} className={quantities[item.id] ? "item-selected" : undefined}><th scope="row">{item.item_name}<small>{item.category_code.replaceAll("_", " ")}{quantities[item.id] ? " · Selected" : ""}</small></th><td className="numeric">{pesos(item.unit_price)}</td>
            <td><div className="quantity"><button className="secondary" type="button" aria-label={`Decrease ${item.item_name}`} disabled={!quantities[item.id]} onClick={() => quantity(item.id, (quantities[item.id] ?? 0) - 1)}>−</button>
              <input aria-label={`${item.item_name} quantity`} type="number" min={0} max={2147483647} step={1} value={quantities[item.id] ?? 0}
                onChange={e => quantity(item.id, Number(e.target.value))} />
              <button className="secondary" type="button" aria-label={`Increase ${item.item_name}`} onClick={() => quantity(item.id, (quantities[item.id] ?? 0) + 1)}>+</button></div></td>
            <td className="numeric">{pesos(itemTotal({ ...menu, items: [item] }, quantities))}</td></tr>)}</tbody></table></div>}
        <p className="total">Order total <strong>{pesos(total)}</strong></p></section>
    </fieldset></div><div className="order-side"><fieldset disabled={saving || !!retry} className="entry-fields"><legend className="sr-only">Payment details</legend>
      <section className="panel payment-panel"><h3><span className="step-number">4</span> Payment allocation</h3>
        <p className="order-checkout-total">Order total <strong>{pesos(total)}</strong></p>
        {kind === "visitor" ? <p>Visitor orders use <strong>Finance</strong>: {pesos(total)}</p> : <>
          <label className="check-label payment-choice"><input type="checkbox" checked={split} onChange={e => setSplit(e.target.checked)} />Split payment</label>
          {!split ? <label>Payment category<select value={payment} onChange={e => setPayment(e.target.value as Payment)}>
            {categories.map(code => <option key={code} value={code}>{paymentLabels[code]}</option>)}</select></label> : <div className="allocation-grid">
            {categories.map(code => <label key={code}>{paymentLabels[code]}<input type="text" inputMode="decimal" placeholder="0.00" value={amounts[code] ?? ""}
              onChange={e => setAmounts(current => ({ ...current, [code]: e.target.value }))} maxLength={13} /></label>)}</div>}
        </>}
        <div className="allocation-summary" aria-live="polite"><span>Allocated <strong>{allocated === null ? "Enter valid amounts" : pesos(allocated)}</strong></span>
          <span>{allocated !== null && allocated > total ? "Over-allocated" : "Remaining"} <strong>{allocated === null ? "—" : pesos(allocated > total ? allocated - total : total - allocated)}</strong></span></div>
        <p className="allocation-readiness" role="status">{allocated !== null && total > BigInt(0) && allocations.length > 0 && allocated === total ? "Allocations balanced for Received." : "Allocations must balance before Received."}</p>
        <p className="muted">Pending orders may have incomplete allocations. Amounts must balance before marking Received. These categories do not verify external payments.</p>
      </section>
    </fieldset>
    <div className="action-bar order-actions"><span className="muted">Save as Pending, then review before marking Received.</span><button type="button" onClick={() => void save()}
      disabled={saving || loading || !menu || !customer || total <= BigInt(0) || allocated === null}>
      {saving ? "Saving…" : retry ? "Retry same order" : "Save Pending order"}</button></div></div></div>
  </div>;
}
