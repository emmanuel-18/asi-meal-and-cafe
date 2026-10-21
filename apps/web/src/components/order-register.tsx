"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { OrderDetail, OrderSummary, RequestApi, Session } from "@/lib/api";
import { canConfirm, canReverse, centavos, operationalToday, paymentLabels, pesos, reasons, type Reason } from "@/lib/meal";
import { canEditPending } from "@/lib/pending-edit";
import PendingOrderEditor from "./pending-order-editor";

export default function OrderRegister({ request, session, savedId }: { request: RequestApi; session: Session; savedId: number | null }) {
  const [day, setDay] = useState(operationalToday);
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [detail, setDetail] = useState<OrderDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(!!savedId);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(savedId ? `Order #${savedId} saved as Pending.` : "");
  const [reversing, setReversing] = useState(false);
  const [reason, setReason] = useState<Reason>("mistaken_click");
  const [explanation, setExplanation] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const detailRequest = useRef<AbortController | null>(null);
  const mutation = useRef(false);

  const load = useCallback((signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: "20", offset: String(offset) });
    if (day) { query.set("start", day); query.set("end", day); }
    if (status) query.set("status", status);
    return request<OrderSummary[]>(`/api/orders?${query}`, { signal }).then(setOrders)
      .finally(() => { if (!signal?.aborted) setLoading(false); });
  }, [day, status, offset, request]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch(error => {
      if (!(error instanceof Error && error.name === "AbortError")) { setOrders([]); setError(error instanceof Error ? error.message : "Unable to load orders."); }
    });
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    if (!savedId) return;
    const controller = new AbortController();
    detailRequest.current = controller;
    void request<OrderDetail>(`/api/orders/${savedId}`, { signal: controller.signal }).then(saved => {
      setDetail(saved); setDay(saved.service_date); setOffset(0);
    }).catch(error => {
      if (!(error instanceof Error && error.name === "AbortError")) setError(error instanceof Error ? error.message : "Unable to load saved order.");
    }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [savedId, request]);
  useEffect(() => () => detailRequest.current?.abort(), []);

  async function open(id: number) {
    detailRequest.current?.abort(); const controller = new AbortController(); detailRequest.current = controller;
    setDetail(null); setEditing(false); setDetailLoading(true); setError(""); setReversing(false); setAcknowledged(false); setExplanation(""); setReason("mistaken_click");
    try { setDetail(await request<OrderDetail>(`/api/orders/${id}`, { signal: controller.signal })); }
    catch (error) { if (!(error instanceof Error && error.name === "AbortError")) setError(error instanceof Error ? error.message : "Unable to load order."); }
    finally { if (!controller.signal.aborted) setDetailLoading(false); }
  }

  async function transition(reverse: boolean) {
    if (!detail || mutation.current) return;
    mutation.current = true; setBusy(true); setError(""); setNotice("");
    const id = detail.order_id;
    try {
      await request(`/api/orders/${id}/${reverse ? "reverse-received" : "received"}`, { method: "POST", body: reverse ?
        { expected_version: detail.version, reason_code: reason, acknowledged, explanation: explanation.trim() || null } :
        { expected_version: detail.version } });
      setDetail(null); setReversing(false); setAcknowledged(false);
      setNotice(`Order #${id} ${reverse ? "returned to Pending" : "marked Received"}.`);
      await open(id); await load();
    } catch (error) {
      // Re-read after any uncertain write or stale version; never retry with a new version automatically.
      setDetail(null); setReversing(false); setAcknowledged(false);
      try { await open(id); await load(); } catch { /* The original error remains actionable. */ }
      setError(error instanceof Error ? error.message : "The change could not be confirmed. Refresh and review before retrying.");
    } finally { mutation.current = false; setBusy(false); }
  }

  const recognized = orders.filter(o => o.is_received).reduce((sum, order) => sum + (centavos(order.total, false) ?? BigInt(0)), BigInt(0));
  const pending = orders.filter(o => !o.is_received).reduce((sum, order) => sum + (centavos(order.total, false) ?? BigInt(0)), BigInt(0));
  const total = detail?.items.reduce((sum, item) => sum + (centavos(item.line_total) ?? BigInt(0)), BigInt(0)) ?? BigInt(0);
  const allocated = detail?.allocations.reduce((sum, a) => sum + (centavos(a.amount) ?? BigInt(0)), BigInt(0)) ?? BigInt(0);

  return <>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <section className="panel"><div className="filter-row"><label>Service date<input type="date" value={day} onChange={e => { setLoading(true); setDay(e.target.value); setOffset(0); setError(""); }} disabled={busy || editing} /></label>
      <label>Status<select value={status} onChange={e => { setLoading(true); setStatus(e.target.value); setOffset(0); setError(""); }} disabled={busy || editing}>
        <option value="">All statuses</option><option value="pending">Pending</option><option value="received">Received</option></select></label>
      <button type="button" className="secondary" disabled={loading || busy || editing} onClick={() => { setLoading(true); setError(""); void load().catch(e => setError(e.message)); }}>Refresh orders</button></div>
      {loading ? <p role="status">Loading orders…</p> : !orders.length ? <p role="status" className="muted">No orders match these filters.</p> : <>
        <div className="table-scroll" role="region" aria-label="Orders matching selected filters" tabIndex={0}><table><caption className="sr-only">Orders matching selected filters</caption><thead><tr>
          <th scope="col">Order</th><th scope="col">Service date</th><th scope="col">Customer</th><th scope="col">Status</th><th scope="col">Total</th><th scope="col">Action</th>
        </tr></thead><tbody>{orders.map(order => <tr key={order.order_id}><td>#{order.order_id}</td><td>{order.service_date}</td>
          <td>{order.customer_name}<small>{order.employee_number ?? `Visitor #${order.visitor_id}`}</small></td>
          <td><span className={`badge ${order.is_received ? "received" : "pending"}`}>{order.is_received ? "Received" : "Pending"}</span></td><td>{pesos(order.total)}</td>
          <td><button type="button" className="secondary" disabled={busy || editing} onClick={() => void open(order.order_id)} aria-label={`View order ${order.order_id}`}>View</button></td></tr>)}</tbody></table></div>
        <p className="page-totals">This page only: Received {pesos(recognized)} · Pending {pesos(pending)}</p>
      </>}
      <div className="pagination"><button type="button" className="secondary" disabled={offset === 0 || loading || busy || editing} onClick={() => { setLoading(true); setOffset(Math.max(0, offset - 20)); }}>Previous</button>
        <span>Page {offset / 20 + 1}</span><button type="button" className="secondary" disabled={orders.length < 20 || offset >= 10000 || loading || busy || editing} onClick={() => { setLoading(true); setOffset(offset + 20); }}>Next</button></div>
    </section>
    {detailLoading && <p role="status">Loading order details…</p>}
    {detail && <section className="panel" aria-labelledby="order-detail-heading"><div className="section-heading"><h3 id="order-detail-heading">Order #{detail.order_id}</h3>
      <button type="button" className="secondary" disabled={busy || editing} onClick={() => { detailRequest.current?.abort(); setDetail(null); }}>Close details</button></div>
      <p><strong>{detail.customer_name}</strong> · {detail.employee_number ?? `Visitor #${detail.visitor_id}`} · {detail.service_date}</p>
      <p><span className={`badge ${detail.is_received ? "received" : "pending"}`}>{detail.is_received ? "Received" : "Pending"}</span> <span className="muted">Version {detail.version}</span></p>
      <div className="table-scroll" role="region" aria-label="Saved order items" tabIndex={0}><table><caption className="sr-only">Saved order items</caption><thead><tr><th scope="col">Item</th><th scope="col">Unit price</th><th scope="col">Quantity</th><th scope="col">Line total</th></tr></thead>
        <tbody>{detail.items.map(item => <tr key={item.id}><th scope="row">{item.name}<small>{item.category.replaceAll("_", " ")}</small></th><td>{pesos(item.unit_price)}</td><td>{item.quantity}</td><td>{pesos(item.line_total)}</td></tr>)}</tbody></table></div>
      <p className="total">Saved order total <strong>{pesos(total)}</strong></p><h4>Recorded allocations</h4>
      {!detail.allocations.length ? <p className="muted">No allocations recorded.</p> : <ul className="allocation-list">{detail.allocations.map(a => <li key={a.id}>{paymentLabels[a.category]} <strong>{pesos(a.amount)}</strong></li>)}</ul>}
      <p>Allocated {pesos(allocated)} · Difference {pesos(total - allocated)}</p>
      {editing && canEditPending(session.user.role, detail.is_received) ? <PendingOrderEditor key={`${detail.order_id}-${detail.version}`} order={detail} request={request}
        onCancel={() => setEditing(false)} onReload={async () => { await open(detail.order_id); try { await load(); } catch { setError("Unable to refresh the register. Please retry."); } }}
        onSaved={async saved => {
          setEditing(false); setDetail(saved); setNotice(`Order #${saved.order_id} changes saved. Current version ${saved.version}.`); setError(""); setBusy(true);
          try { await load(); } catch { setOrders([]); setError("The order was saved, but the register could not refresh. Refresh orders to update the list."); }
          finally { setBusy(false); }
        }} /> : !detail.is_received && <div className="action-bar"><p className="muted">Confirm only after meal handover and completion.</p>
        <div className="button-row">{canEditPending(session.user.role, detail.is_received) && <button type="button" className="secondary" disabled={busy || loading}
          onClick={() => { setEditing(true); setError(""); setNotice(""); }}>Edit Pending order</button>}
        <button type="button" disabled={busy || !detail.allocations.length || total !== allocated} onClick={() => void transition(false)}>{busy ? "Saving…" : "Mark Received"}</button></div></div>}
      {canReverse(session.user.role, detail.is_received) && <>
        {!reversing ? <button type="button" className="secondary" disabled={busy} onClick={() => { setReversing(true); setAcknowledged(false); }}>Reverse to Pending</button> : <form className="correction" onSubmit={e => { e.preventDefault(); void transition(true); }}>
          <h4>Received correction</h4><p>This removes the order from current recognized sales and payment-category totals.</p>
          <label>Correction reason<select value={reason} disabled={busy} onChange={e => { setReason(e.target.value as Reason); setAcknowledged(false); }}>
            {reasons.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
          <label>Explanation{reason === "other" ? " (required)" : " (optional)"}<textarea value={explanation} maxLength={2000} required={reason === "other"} disabled={busy}
            onChange={e => { setExplanation(e.target.value); setAcknowledged(false); }} /></label>
          <label className="check-label"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={e => setAcknowledged(e.target.checked)} />I, {session.user.display_name}, confirm this change.</label>
          <div className="button-row"><button type="submit" disabled={busy || !canConfirm(reason, explanation, acknowledged)}>{busy ? "Saving…" : "Confirm reversal"}</button>
            <button type="button" className="secondary" disabled={busy} onClick={() => setReversing(false)}>Cancel</button></div>
        </form>}
      </>}
    </section>}
  </>;
}
