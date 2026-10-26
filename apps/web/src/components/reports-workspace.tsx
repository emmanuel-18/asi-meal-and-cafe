"use client";

import { useEffect, useRef, useState } from "react";
import type { RequestApi } from "@/lib/api";
import { centavos, paymentLabels, pesos } from "@/lib/meal";
import { categoryLabels } from "@/lib/menus";
import { barWidth, initialFilter, loadExportReport, loadReport, matchingEmployees, reportPath, periodLabel, salaryByCampaign, type ReportFilter, type ReportBundle, type ReportMode } from "@/lib/reports";
import { downloadReport } from "@/lib/report-export";

export default function ReportsWorkspace({ request }: { request: RequestApi }) {
  const [filter, setFilter] = useState(initialFilter);
  const [applied, setApplied] = useState<ReportFilter | null>(filter);
  const [revision, setRevision] = useState(0);
  const [bundle, setBundle] = useState<ReportBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [exporting, setExporting] = useState(false);
  const exportRun = useRef<AbortController | null>(null);
  useEffect(() => () => { exportRun.current?.abort(); }, [request]);

  useEffect(() => {
    if (!applied) return;
    const controller = new AbortController();
    void loadReport(request, applied, controller.signal).then(result => { if (!controller.signal.aborted) setBundle(result); }).catch(error => {
      if (!controller.signal.aborted) { setBundle(null); setError(error instanceof Error ? error.message : "Unable to load reports."); }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [request, applied, revision]);

  function updateFilter(next: ReportFilter) {
    exportRun.current?.abort();
    setFilter(next); setBundle(null); setQuery("");
    try { reportPath(next); } catch (error) {
      setApplied(null); setLoading(false);
      setError(error instanceof Error ? error.message : "Choose a valid period."); return;
    }
    setError(""); setLoading(true); setApplied(next);
  }
  function refresh() { exportRun.current?.abort(); setError(""); setBundle(null); setLoading(true); setRevision(value => value + 1); }
  async function exportReport() {
    if (!bundle || !applied || loading || exporting || exportRun.current) return;
    const controller = new AbortController(); exportRun.current = controller;
    setExporting(true); setError("");
    try {
      const data = await loadExportReport(request, applied, bundle.sales.period, controller.signal);
      if (controller.signal.aborted) return;
      await downloadReport(data, applied.mode, "excel", controller.signal);
    } catch (error) { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Unable to download the report. Please try again."); }
    finally { if (exportRun.current === controller) { exportRun.current = null; setExporting(false); } }
  }
  const employees = bundle ? matchingEmployees(bundle, query) : [];
  const grouped = bundle ? salaryByCampaign(bundle.salary_deduction.orders) : null;
  const campaigns = bundle && grouped && grouped.reduce((sum, row) => sum + row.amount, BigInt(0)) === centavos(bundle.salary_deduction.total, false) ? grouped : null;
  const paymentValues = bundle?.payments.totals.map(row => ({ ...row, value: centavos(row.amount, false) })) ?? [];
  const paymentMaximum = paymentValues.reduce((max, row) => row.value !== null && row.value > max ? row.value : max, BigInt(0));

  return <><div className="section-heading"><div><h2>Reports</h2><p className="muted">Recognized sales, payment allocations, and Salary Deduction.</p></div></div>
    <section className="panel report-filters"><h3>Reporting period</h3>
      <form className="filter-row" onSubmit={event => { event.preventDefault(); if (applied) refresh(); }}>
        <label>Period<select value={filter.mode} onChange={event => updateFilter({ ...filter, mode: event.target.value as ReportMode })}>
          <option value="daily">Daily</option><option value="weekly">Weekly (Monday–Sunday)</option><option value="monthly">Monthly</option><option value="custom">Custom range</option></select></label>
        {(filter.mode === "daily" || filter.mode === "weekly") && <label>{filter.mode === "weekly" ? "Date in week" : "Date"}<input type="date" required value={filter.day} onChange={event => updateFilter({ ...filter, day: event.target.value })} /></label>}
        {filter.mode === "monthly" && <label>Month<input type="month" required value={filter.month} onChange={event => updateFilter({ ...filter, month: event.target.value })} /></label>}
        {filter.mode === "custom" && <><label>Start date<input type="date" required value={filter.start} onChange={event => updateFilter({ ...filter, start: event.target.value })} /></label>
          <label>End date<input type="date" required value={filter.end} onChange={event => updateFilter({ ...filter, end: event.target.value })} /></label></>}
        <button type="submit" className="secondary" disabled={loading || !applied}>Refresh report</button>
        <button type="button" className="report-download-excel" disabled={!bundle || loading || exporting} aria-busy={exporting}
          onClick={() => void exportReport()}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3v12m-4-4 4 4 4-4M4 17v3h16v-3" /></svg>
          {exporting ? "Preparing Excel..." : "Download Excel"}
        </button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}{loading && <p role="status">Loading report…</p>}
      {bundle && applied && <p className="report-period" role="status"><strong>{periodLabel(applied.mode, bundle.sales.period)}</strong><br /><span className="muted">{bundle.sales.period.start} through {bundle.sales.period.end} · Inclusive · Philippine time</span></p>}
    </section>
    {bundle && !loading && <>
      <section className="report-kpis" aria-label="Report overview">
        <div><span>Recognized sales</span><strong>{pesos(bundle.sales.recognized_sales)}</strong></div>
        <div><span>Received orders</span><strong>{bundle.sales.received_order_count}</strong></div>
        <div><span>Salary Deduction</span><strong>{pesos(bundle.salary_deduction.total)}</strong></div>
        <div><span>Total allocated</span><strong>{pesos(bundle.payments.total)}</strong></div>
      </section>
      <div className="report-charts">
        <section className="panel report-chart" aria-labelledby="payment-chart-title"><h3 id="payment-chart-title">Payment allocations</h3>
          {paymentValues.some(row => row.value === null) ? <p role="alert">Payment breakdown is unavailable.</p> : paymentValues.length === 0 ? <p role="status">No payment allocations in this period.</p> : <ul>{paymentValues.map(row => <li key={row.category} className={row.value === BigInt(0) ? "report-zero" : undefined}><span>{paymentLabels[row.category]}</span><strong>{pesos(row.amount)}</strong><div className="report-bar" aria-hidden="true"><span style={{ width: barWidth(row.value ?? BigInt(0), paymentMaximum) }} /></div></li>)}</ul>}
        </section>
        <section className="panel report-chart" aria-labelledby="campaign-chart-title"><h3 id="campaign-chart-title">Salary Deduction by recorded campaign</h3><p className="muted">Total: {pesos(bundle.salary_deduction.total)}</p>
          {campaigns === null ? <p role="alert">Campaign breakdown is unavailable.</p> : campaigns.length === 0 ? <p role="status">No Salary Deduction allocations in this period.</p> : <ul>{campaigns.map(row => <li key={row.name}><span>{row.name}</span><strong>{pesos(row.amount)}</strong><div className="report-bar" aria-hidden="true"><span style={{ width: barWidth(row.amount, campaigns[0].amount) }} /></div></li>)}</ul>}
        </section>
      </div>
      <section className="panel"><h3>Sales summary</h3>
        <div className="allocation-summary sales-summary"><span>Meals <strong>{bundle.sales.meal_quantity}</strong></span><span>Items <strong>{bundle.sales.item_quantity}</strong></span></div>
        {bundle.sales.received_order_count === 0 && <p className="muted" role="status">No Received orders in this period.</p>}
        <div className="table-scroll" role="region" aria-label="Sales by recorded category" tabIndex={0}><table><caption>Sales by recorded category</caption><thead><tr><th scope="col">Category</th><th scope="col" className="numeric">Quantity</th><th scope="col" className="numeric">Sales</th></tr></thead>
          <tbody>{bundle.sales.categories.map(row => <tr key={row.category}><th scope="row">{categoryLabels[row.category]}</th><td className="numeric">{row.quantity}</td><td className="numeric">{pesos(row.amount)}</td></tr>)}</tbody></table></div>
        {bundle.sales.items.length > 0 && <div className="table-scroll" role="region" aria-label="Recorded item sales" tabIndex={0}><table><caption>Recorded item sales</caption><thead><tr><th scope="col">Item</th><th scope="col">Category</th><th scope="col" className="numeric">Recorded unit price</th><th scope="col" className="numeric">Quantity</th><th scope="col" className="numeric">Sales</th></tr></thead>
          <tbody>{bundle.sales.items.map((item, index) => <tr key={`${item.source_menu_item_id}-${index}`}><th scope="row">{item.item_name}</th><td>{categoryLabels[item.category]}</td><td className="numeric">{pesos(item.unit_price)}</td><td className="numeric">{item.quantity}</td><td className="numeric">{pesos(item.amount)}</td></tr>)}</tbody></table></div>}
      </section>
      <section className="panel"><h3>Payment allocations</h3><p className="muted">Amounts are allocated by payment category; split orders contribute their allocation to each category.</p>
        <div className="table-scroll" role="region" aria-label="Payment-category allocations" tabIndex={0}><table><caption className="sr-only">Payment-category allocations</caption><thead><tr><th scope="col">Category</th><th scope="col" className="numeric">Allocated amount</th></tr></thead>
          <tbody>{bundle.payments.totals.map(row => <tr key={row.category}><th scope="row">{paymentLabels[row.category]}</th><td className="numeric">{pesos(row.amount)}</td></tr>)}</tbody>
          <tfoot><tr><th scope="row">Total allocated</th><td className="numeric">{pesos(bundle.payments.total)}</td></tr></tfoot></table></div>
      </section>
      <section className="panel"><h3>Salary Deduction</h3><p className="total sd-total">Total SD allocated <strong>{pesos(bundle.salary_deduction.total)}</strong></p>
        <p className="muted">This records SD allocations, not payroll completion. Names and organizational details below are the snapshots recorded on each order.</p>
        {bundle.salary_deduction.employees.length === 0 ? <p role="status" className="muted">No Salary Deduction allocations in this period.</p> : <>
          <label className="report-search">Search employee number or recorded name<input value={query} onChange={event => setQuery(event.target.value)} maxLength={100} /></label>
          {!employees.length ? <p role="status" className="muted">No employees match this search.</p> : employees.map(employee => <div className="sd-employee" key={employee.employee_number}>
            <h4>Employee {employee.employee_number}</h4><p>{employee.order_count} {employee.order_count === 1 ? "order" : "orders"} · SD total: <strong>{pesos(employee.sd_amount)}</strong></p>
            <div className="table-scroll" role="region" aria-label="Recorded salary deduction orders" tabIndex={0}><table><caption className="sr-only">Recorded SD order snapshots for employee {employee.employee_number}</caption><thead><tr><th scope="col">Date / order</th><th scope="col">Recorded name</th><th scope="col">Position</th><th scope="col">Campaign</th><th scope="col">Line of business</th><th scope="col" className="numeric">SD amount</th></tr></thead>
              <tbody>{bundle.salary_deduction.orders.filter(order => order.employee_number === employee.employee_number).map(order => <tr key={order.order_id}><th scope="row">{order.service_date}<small>Order #{order.order_id}</small></th><td>{order.customer_name}</td><td>{order.position || "—"}</td><td>{order.campaign || "—"}</td><td>{order.line_of_business || "—"}</td><td className="numeric">{pesos(order.sd_amount)}</td></tr>)}</tbody></table></div>
          </div>)}
        </>}
      </section>
    </>}
  </>;
}
