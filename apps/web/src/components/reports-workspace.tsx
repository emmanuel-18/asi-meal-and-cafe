"use client";

import { useEffect, useState } from "react";
import type { RequestApi } from "@/lib/api";
import { paymentLabels, pesos } from "@/lib/meal";
import { categoryLabels } from "@/lib/menus";
import { initialFilter, loadReport, matchingEmployees, reportPath, type ReportBundle, type ReportMode } from "@/lib/reports";

export default function ReportsWorkspace({ request }: { request: RequestApi }) {
  const [filter, setFilter] = useState(initialFilter);
  const [applied, setApplied] = useState(filter);
  const [revision, setRevision] = useState(0);
  const [bundle, setBundle] = useState<ReportBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void loadReport(request, applied, controller.signal).then(result => { if (!controller.signal.aborted) setBundle(result); }).catch(error => {
      if (!controller.signal.aborted) { setBundle(null); setError(error instanceof Error ? error.message : "Unable to load reports."); }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [request, applied, revision]);

  function apply(event: React.FormEvent) {
    event.preventDefault();
    try { reportPath(filter); } catch (error) { setError(error instanceof Error ? error.message : "Choose a valid period."); return; }
    setError(""); setBundle(null); setLoading(true); setApplied({ ...filter }); setQuery("");
  }
  function refresh() { setError(""); setBundle(null); setLoading(true); setRevision(value => value + 1); }
  const employees = bundle ? matchingEmployees(bundle, query) : [];

  return <><div className="section-heading"><h2>Reports</h2></div>
    <section className="panel"><h3>Reporting period</h3>
      <form className="filter-row" onSubmit={apply}>
        <label>Period<select value={filter.mode} onChange={event => setFilter({ ...filter, mode: event.target.value as ReportMode })}>
          <option value="daily">Daily</option><option value="weekly">Weekly (Monday–Sunday)</option><option value="monthly">Monthly</option><option value="custom">Custom range</option></select></label>
        {(filter.mode === "daily" || filter.mode === "weekly") && <label>{filter.mode === "weekly" ? "Date in week" : "Date"}<input type="date" required value={filter.day} onChange={event => setFilter({ ...filter, day: event.target.value })} /></label>}
        {filter.mode === "monthly" && <label>Month<input type="month" required value={filter.month} onChange={event => setFilter({ ...filter, month: event.target.value })} /></label>}
        {filter.mode === "custom" && <><label>Start date<input type="date" required value={filter.start} onChange={event => setFilter({ ...filter, start: event.target.value })} /></label>
          <label>End date<input type="date" required value={filter.end} onChange={event => setFilter({ ...filter, end: event.target.value })} /></label></>}
        <button type="submit" disabled={loading}>View report</button><button type="button" className="secondary" onClick={refresh} disabled={loading}>Refresh current report</button>
      </form>
      <p className="muted">Dates are inclusive and use the Philippine operational calendar. Only currently Received orders are included. Refresh to see corrections.</p>
      {error && <p className="error" role="alert">{error}</p>}{loading && <p role="status">Loading report…</p>}
      {bundle && <p role="status"><strong>Showing {bundle.sales.period.start} through {bundle.sales.period.end}</strong> (inclusive)</p>}
    </section>
    {bundle && !loading && <>
      <section className="panel"><h3>Sales summary</h3>
        <div className="allocation-summary"><span>Recognized sales <strong>{pesos(bundle.sales.recognized_sales)}</strong></span><span>Received orders <strong>{bundle.sales.received_order_count}</strong></span><span>Meals <strong>{bundle.sales.meal_quantity}</strong></span><span>Items <strong>{bundle.sales.item_quantity}</strong></span></div>
        {bundle.sales.received_order_count === 0 && <p className="muted" role="status">No Received orders in this period.</p>}
        <div className="table-scroll" role="region" aria-label="Sales by recorded category" tabIndex={0}><table><caption>Sales by recorded category</caption><thead><tr><th scope="col">Category</th><th scope="col">Quantity</th><th scope="col">Sales</th></tr></thead>
          <tbody>{bundle.sales.categories.map(row => <tr key={row.category}><th scope="row">{categoryLabels[row.category]}</th><td>{row.quantity}</td><td>{pesos(row.amount)}</td></tr>)}</tbody></table></div>
        {bundle.sales.items.length > 0 && <div className="table-scroll" role="region" aria-label="Recorded item sales" tabIndex={0}><table><caption>Recorded item sales</caption><thead><tr><th scope="col">Item</th><th scope="col">Category</th><th scope="col">Recorded unit price</th><th scope="col">Quantity</th><th scope="col">Sales</th></tr></thead>
          <tbody>{bundle.sales.items.map((item, index) => <tr key={`${item.source_menu_item_id}-${index}`}><th scope="row">{item.item_name}</th><td>{categoryLabels[item.category]}</td><td>{pesos(item.unit_price)}</td><td>{item.quantity}</td><td>{pesos(item.amount)}</td></tr>)}</tbody></table></div>}
      </section>
      <section className="panel"><h3>Payment allocations</h3><p className="muted">Amounts are allocated by payment category; split orders contribute their allocation to each category.</p>
        <div className="table-scroll" role="region" aria-label="Payment-category allocations" tabIndex={0}><table><caption className="sr-only">Payment-category allocations</caption><thead><tr><th scope="col">Category</th><th scope="col">Allocated amount</th></tr></thead>
          <tbody>{bundle.payments.totals.map(row => <tr key={row.category}><th scope="row">{paymentLabels[row.category]}</th><td>{pesos(row.amount)}</td></tr>)}</tbody>
          <tfoot><tr><th scope="row">Total allocated</th><td>{pesos(bundle.payments.total)}</td></tr></tfoot></table></div>
      </section>
      <section className="panel"><h3>Salary Deduction</h3><p>Total SD allocated: <strong>{pesos(bundle.salary_deduction.total)}</strong></p>
        <p className="muted">This records SD allocations, not payroll completion. Names and organizational details below are the snapshots recorded on each order.</p>
        {bundle.salary_deduction.employees.length === 0 ? <p role="status" className="muted">No Salary Deduction allocations in this period.</p> : <>
          <label className="report-search">Search employee number or recorded name<input value={query} onChange={event => setQuery(event.target.value)} maxLength={100} /></label>
          {!employees.length ? <p role="status" className="muted">No employees match this search.</p> : employees.map(employee => <div className="sd-employee" key={employee.employee_number}>
            <h4>Employee {employee.employee_number}</h4><p>{employee.order_count} {employee.order_count === 1 ? "order" : "orders"} · SD total: <strong>{pesos(employee.sd_amount)}</strong></p>
            <div className="table-scroll" role="region" aria-label="Recorded salary deduction orders" tabIndex={0}><table><caption className="sr-only">Recorded SD order snapshots for employee {employee.employee_number}</caption><thead><tr><th scope="col">Date / order</th><th scope="col">Recorded name</th><th scope="col">Position</th><th scope="col">Campaign</th><th scope="col">Line of business</th><th scope="col">SD amount</th></tr></thead>
              <tbody>{bundle.salary_deduction.orders.filter(order => order.employee_number === employee.employee_number).map(order => <tr key={order.order_id}><th scope="row">{order.service_date}<small>Order #{order.order_id}</small></th><td>{order.customer_name}</td><td>{order.position || "—"}</td><td>{order.campaign || "—"}</td><td>{order.line_of_business || "—"}</td><td>{pesos(order.sd_amount)}</td></tr>)}</tbody></table></div>
          </div>)}
        </>}
      </section>
    </>}
  </>;
}
