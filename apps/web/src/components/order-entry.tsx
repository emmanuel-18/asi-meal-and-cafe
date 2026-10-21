"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type Allocation, type Menu, type OrderInput, type OrderResult, type Payment, type RequestApi } from "@/lib/api";
import { allocationTotal, buildOrder, decimal, itemTotal, operationalToday, paymentLabels, pesos } from "@/lib/meal";
import CustomerPicker, { type Customer } from "./customer-picker";

export default function OrderEntry({ request, onSaved }: { request: RequestApi; onSaved: (id: number) => void }) {
  const [day, setDay] = useState(operationalToday);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [kind, setKind] = useState<"employee" | "visitor">("employee");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [split, setSplit] = useState(false);
  const [payment, setPayment] = useState<Payment>("cash");
  const [amounts, setAmounts] = useState<Partial<Record<Payment, string>>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState<OrderInput | null>(null);
  const submitted = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const total = menu ? itemTotal(menu, quantities) : BigInt(0);
  const categories = Object.keys(paymentLabels) as Payment[];
  const allocations: Allocation[] = kind === "visitor" ? [{ category: "finance", amount: decimal(total) }] : split ?
    categories.filter(code => (amounts[code] ?? "").trim() !== "").map(code => ({ category: code, amount: amounts[code]! })) :
    [{ category: payment, amount: decimal(total) }];
  const allocated = allocationTotal(allocations);

  async function loadMenu(event: React.FormEvent) {
    event.preventDefault(); controller.current?.abort();
    const current = new AbortController(); controller.current = current;
    setLoading(true); setMenu(null); setQuantities({}); setError("");
    try { setMenu(await request<Menu>(`/api/menus/by-date/${encodeURIComponent(day)}`, { signal: current.signal })); }
    catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) setError(error instanceof ApiError && error.status === 404 ?
        "No menu is assigned to this service date. Select another date or ask staff to configure it." : error instanceof Error ? error.message : "Unable to load menu.");
    } finally { if (!current.signal.aborted) setLoading(false); }
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

  return <div>
    {error && <p className="error" role="alert">{error}</p>}
    {retry && !saving && <p className="notice" role="status">The result could not be confirmed. Retry the same order below; its request key prevents duplicate processing. Check the order list before starting another order.</p>}
    <fieldset disabled={saving || !!retry} className="entry-fields"><legend className="sr-only">New order details</legend>
      <section className="panel"><h3>1. Service date</h3><form onSubmit={loadMenu} className="inline-form">
        <label>Menu service date<input type="date" required value={day} onChange={e => {
          controller.current?.abort(); setLoading(false); setDay(e.target.value); setMenu(null); setQuantities({}); setError("");
        }} /></label><button type="submit" disabled={loading}>{loading ? "Loading menu…" : "Load menu"}</button>
      </form>{menu && <p className="muted">{menu.label || `Menu #${menu.id}`} · {menu.service_date}</p>}</section>
      <section className="panel"><h3>2. Customer</h3><fieldset className="choice-row"><legend>Customer type</legend>
        {(["employee", "visitor"] as const).map(value => <label key={value}><input type="radio" name="customer-kind" checked={kind === value}
          onChange={() => { setKind(value); setCustomer(null); setSplit(false); setAmounts({}); }} />{value === "employee" ? "Employee" : "Visitor"}</label>)}
      </fieldset>
      <CustomerPicker key={kind} kind={kind} request={request} selected={customer} onSelect={setCustomer} /></section>
      <section className="panel"><h3>3. Menu items</h3>{!menu ? <p className="muted">Load an assigned menu to select items.</p> : !menu.items.length ?
        <p className="muted">This menu has no offerings. Ask staff to configure it.</p> : <div className="table-scroll" role="region" aria-label="Menu offerings and quantities" tabIndex={0}><table><caption className="sr-only">Menu offerings and quantities</caption>
          <thead><tr><th scope="col">Dish</th><th scope="col">Unit price</th><th scope="col">Quantity</th><th scope="col">Line total</th></tr></thead>
          <tbody>{menu.items.map(item => <tr key={item.id}><th scope="row">{item.item_name}<small>{item.category_code.replaceAll("_", " ")}</small></th><td>{pesos(item.unit_price)}</td>
            <td><div className="quantity"><button className="secondary" type="button" aria-label={`Decrease ${item.item_name}`} disabled={!quantities[item.id]} onClick={() => quantity(item.id, (quantities[item.id] ?? 0) - 1)}>−</button>
              <input aria-label={`${item.item_name} quantity`} type="number" min={0} max={2147483647} step={1} value={quantities[item.id] ?? 0}
                onChange={e => quantity(item.id, Number(e.target.value))} />
              <button className="secondary" type="button" aria-label={`Increase ${item.item_name}`} onClick={() => quantity(item.id, (quantities[item.id] ?? 0) + 1)}>+</button></div></td>
            <td>{pesos(itemTotal({ ...menu, items: [item] }, quantities))}</td></tr>)}</tbody></table></div>}
        <p className="total">Order total <strong>{pesos(total)}</strong></p></section>
      <section className="panel"><h3>4. Payment allocation</h3>
        {kind === "visitor" ? <p>Visitor orders use <strong>Finance</strong>: {pesos(total)}</p> : <>
          <label className="check-label"><input type="checkbox" checked={split} onChange={e => setSplit(e.target.checked)} />Split Payment</label>
          {!split ? <label>Payment category<select value={payment} onChange={e => setPayment(e.target.value as Payment)}>
            {categories.map(code => <option key={code} value={code}>{paymentLabels[code]}</option>)}</select></label> : <div className="allocation-grid">
            {categories.map(code => <label key={code}>{paymentLabels[code]}<input type="text" inputMode="decimal" placeholder="0.00" value={amounts[code] ?? ""}
              onChange={e => setAmounts(current => ({ ...current, [code]: e.target.value }))} maxLength={13} /></label>)}</div>}
        </>}
        <div className="allocation-summary" aria-live="polite"><span>Allocated <strong>{allocated === null ? "Enter valid amounts" : pesos(allocated)}</strong></span>
          <span>Difference <strong>{allocated === null ? "—" : pesos(total - allocated)}</strong></span></div>
        <p className="muted">Pending orders may have incomplete allocations. Amounts must balance before marking Received. These categories do not verify external payments.</p>
      </section>
    </fieldset>
    <div className="action-bar"><span className="muted">Save first as Pending.</span><button type="button" onClick={() => void save()}
      disabled={saving || loading || !menu || !customer || total <= BigInt(0) || allocated === null}>
      {saving ? "Saving…" : retry ? "Retry same order" : "Save Pending order"}</button></div>
  </div>;
}
