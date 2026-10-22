"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { OrderDetail, OrderSummary, RequestApi, Session } from "@/lib/api";
import { listingError, loadOrderPage, receiveError } from "@/lib/order-register";
import { canConfirm, canReverse, centavos, operationalToday, paymentLabels, pesos, reasons, type Reason } from "@/lib/meal";
import { canEditPending } from "@/lib/pending-edit";
import PendingOrderEditor from "./pending-order-editor";

export default function OrderRegister({ request, session, savedId }: { request: RequestApi; session: Session; savedId: number | null }) {
  const [day, setDay] = useState(operationalToday);
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [listingInvalid, setListingInvalid] = useState(false);
  const [overview, setOverview] = useState<{ pending: number; received: number; total: number; recognized_sales: string } | null>(null);
  const [overviewError, setOverviewError] = useState("");
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
  const listingRevision = useRef<string | null>(null);

  const load = useCallback((signal?: AbortSignal, pageOffset = offset) => {
    if (pageOffset === 0) listingRevision.current = null;
    return loadOrderPage(request, day, status, pageOffset, listingRevision.current, signal).then(result => {
      if (!signal?.aborted) { listingRevision.current = result.revision; setListingInvalid(false); setOrders(result.orders); }
    })
      .finally(() => { if (!signal?.aborted) setLoading(false); });
  }, [day, status, offset, request]);

  const loadOverview = useCallback(async (signal?: AbortSignal) => {
    if (!day) { setOverview(null); return; }
    setOverview(null); setOverviewError("");
    try { const result = await request<{ pending: number; received: number; total: number; recognized_sales: string }>(`/api/orders/overview?day=${encodeURIComponent(day)}`, { signal }); if (!signal?.aborted) setOverview(result); }
    catch (error) { if (!signal?.aborted) setOverviewError(error instanceof Error ? error.message : "Unable to load date totals."); }
  }, [day, request]);

  useEffect(() => { const controller = new AbortController(); void Promise.resolve().then(() => { if (!controller.signal.aborted) return loadOverview(controller.signal); }); return () => controller.abort(); }, [loadOverview]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch(error => {
      if (!(error instanceof Error && error.name === "AbortError")) { listingRevision.current = null; setListingInvalid(true); setOrders([]); setError(listingError(error)); }
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
      await open(id); setOffset(0); await Promise.all([load(undefined, 0), loadOverview()]);
    } catch (error) {
      // Re-read after any uncertain write or stale version; never retry with a new version automatically.
      setDetail(null); setReversing(false); setAcknowledged(false);
      try { await open(id); setOffset(0); await Promise.all([load(undefined, 0), loadOverview()]); } catch { /* The original error remains actionable. */ }
      setError(error instanceof Error ? error.message : "The change could not be confirmed. Refresh and review before retrying.");
    } finally { mutation.current = false; setBusy(false); }
  }

  async function quickReceive(order: OrderSummary) {
    if (mutation.current || editing) return;
    mutation.current = true; setBusy(true); setError(""); setNotice("");
    let confirmed = false;
    try {
      await request(`/api/orders/${order.order_id}/received`, { method: "POST", body: { expected_version: order.version } });
      confirmed = true;
      setNotice(`Order #${order.order_id} marked Received.`); setOffset(0);
      await Promise.all([load(undefined, 0), loadOverview()]);
      if (detail?.order_id === order.order_id) await open(order.order_id);
    } catch (error) {
      setOffset(0); try { await Promise.all([load(undefined, 0), loadOverview()]); await open(order.order_id); } catch { /* Review before retrying. */ }
      setError(confirmed ? "The order was marked Received, but the register could not refresh. Refresh orders to review." : receiveError(error));
    } finally { mutation.current = false; setBusy(false); }
  }

  const total = detail?.items.reduce((sum, item) => sum + (centavos(item.line_total) ?? BigInt(0)), BigInt(0)) ?? BigInt(0);
  const allocated = detail?.allocations.reduce((sum, a) => sum + (centavos(a.amount) ?? BigInt(0)), BigInt(0)) ?? BigInt(0);

  return <>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <section className="order-overview" aria-label="Selected service date overview">{!day ? <p>Select a service date for totals.</p> : overviewError ? <p role="alert" className="error">Date totals: {overviewError}</p> : !overview ? <p role="status">Loading date totals...</p> : <><div><span>Pending</span><strong>{overview.pending}</strong></div><div><span>Received</span><strong>{overview.received}</strong></div><div><span>Total orders</span><strong>{overview.total}</strong></div><div><span>Recognized sales</span><strong>{pesos(overview.recognized_sales)}</strong></div></>}</section>
    <section className="panel"><div className="filter-row"><label>Service date<input type="date" value={day} onChange={e => { listingRevision.current = null; setLoading(true); setDay(e.target.value); setOffset(0); setError(""); }} disabled={busy || editing} /></label>
      <label>Status<select value={status} onChange={e => { listingRevision.current = null; setLoading(true); setStatus(e.target.value); setOffset(0); setError(""); }} disabled={busy || editing}>
        <option value="">All statuses</option><option value="pending">Pending</option><option value="received">Received</option></select></label>
      <button type="button" className="secondary" disabled={loading || busy || editing} onClick={() => { setLoading(true); setError(""); setOffset(0); void load(undefined, 0).catch(e => setError(e.message)); void loadOverview(); }}>Refresh orders</button></div>
      {loading ? <p role="status">Loading orders…</p> : !orders.length ? <p role="status" className="muted">No orders match these filters.</p> : <>
        <div className="table-scroll" role="region" aria-label="Orders matching selected filters" tabIndex={0}><table><caption className="sr-only">Orders matching selected filters</caption><thead><tr>
          <th scope="col">Order</th><th scope="col">Service date</th><th scope="col">Customer</th><th scope="col">Status</th><th scope="col" className="numeric">Total</th><th scope="col">Action</th>
        </tr></thead><tbody>{orders.map(order => <tr key={order.order_id} className={`order-row${detail?.order_id === order.order_id ? " selected" : ""}`} tabIndex={busy || editing ? -1 : 0} aria-label={`Open order ${order.order_id}`} onClick={() => { if (!busy && !editing) void open(order.order_id); }} onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); if (!busy && !editing) void open(order.order_id); } }}><td>#{order.order_id}</td><td>{order.service_date}</td>
          <td>{order.customer_name}<small>{order.employee_number ?? `Visitor #${order.visitor_id}`}</small></td>
          <td><span className={`badge ${order.is_received ? "received" : "pending"}`}>{order.is_received ? "Received" : "Pending"}</span></td><td className="numeric">{pesos(order.total)}</td>
          <td>{!order.is_received && <button type="button" disabled={busy || editing} onClick={event => { event.stopPropagation(); void quickReceive(order); }} aria-label={`Mark order ${order.order_id} Received`}>Mark Received</button>}</td></tr>)}</tbody></table></div>
      </>}
      <div className="pagination"><button type="button" className="secondary" disabled={listingInvalid || offset === 0 || loading || busy || editing} onClick={() => { setLoading(true); setOffset(Math.max(0, offset - 20)); }}>Previous</button>
        <span>Page {offset / 20 + 1}</span><button type="button" className="secondary" disabled={orders.length < 20 || offset >= 10000 || loading || busy || editing} onClick={() => { setLoading(true); setOffset(offset + 20); }}>Next</button></div>
    </section>
    {detailLoading && <p role="status">Loading order details…</p>}
    {detail && <section className="panel" aria-labelledby="order-detail-heading"><div className="section-heading"><h3 id="order-detail-heading">Order #{detail.order_id}</h3>
      <button type="button" className="secondary" disabled={busy || editing} onClick={() => { detailRequest.current?.abort(); setDetail(null); }}>Close details</button></div>
      <p><strong>{detail.customer_name}</strong> · {detail.employee_number ?? `Visitor #${detail.visitor_id}`} · {detail.service_date}</p>
      <p><span className={`badge ${detail.is_received ? "received" : "pending"}`}>{detail.is_received ? "Received" : "Pending"}</span> <span className="muted">Version {detail.version}</span></p>
      <div className="table-scroll" role="region" aria-label="Saved order items" tabIndex={0}><table><caption className="sr-only">Saved order items</caption><thead><tr><th scope="col">Item</th><th scope="col" className="numeric">Unit price</th><th scope="col" className="numeric">Quantity</th><th scope="col" className="numeric">Line total</th></tr></thead>
        <tbody>{detail.items.map(item => <tr key={item.id}><th scope="row">{item.name}<small>{item.category.replaceAll("_", " ")}</small></th><td className="numeric">{pesos(item.unit_price)}</td><td className="numeric">{item.quantity}</td><td className="numeric">{pesos(item.line_total)}</td></tr>)}</tbody></table></div>
      <p className="total">Saved order total <strong>{pesos(total)}</strong></p><h4>Recorded allocations</h4>
      {!detail.allocations.length ? <p className="muted">No allocations recorded.</p> : <ul className="allocation-list">{detail.allocations.map(a => <li key={a.id}>{paymentLabels[a.category]} <strong>{pesos(a.amount)}</strong></li>)}</ul>}
      <div className="allocation-summary"><span>Allocated <strong>{pesos(allocated)}</strong></span><span>Difference <strong>{pesos(total - allocated)}</strong></span></div>
      {editing && canEditPending(session.user.role, detail.is_received) ? <PendingOrderEditor key={`${detail.order_id}-${detail.version}`} order={detail} request={request}
        onCancel={() => setEditing(false)} onReload={async () => { await open(detail.order_id); try { await load(); } catch { setError("Unable to refresh the register. Please retry."); } }}
        onSaved={async saved => {
          setEditing(false); setDetail(saved); setNotice(`Order #${saved.order_id} changes saved. Current version ${saved.version}.`); setError(""); setBusy(true);
          setOffset(0);
          try { await load(undefined, 0); } catch { setOrders([]); setError("The order was saved, but the register could not refresh. Refresh orders to update the list."); }
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
