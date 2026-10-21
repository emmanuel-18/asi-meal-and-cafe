"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type RecordedMenu, type RequestApi } from "@/lib/api";
import { addDate, assignMenu, inspectDates, needsReplacement, type ReviewedDate } from "@/lib/menus";

export default function MenuScheduling({ menu, request }: { menu: RecordedMenu; request: RequestApi }) {
  const [day, setDay] = useState("");
  const [dates, setDates] = useState<string[]>([]);
  const [reviewed, setReviewed] = useState<ReviewedDate[] | null>(null);
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const submitting = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  function invalidate() { setReviewed(null); setConfirmed([]); setNotice(""); setError(""); }
  async function review() {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); invalidate();
    const current = new AbortController(); controller.current = current;
    try { setReviewed(await inspectDates(request, dates, current.signal)); }
    catch (error) { if (!(error instanceof Error && error.name === "AbortError")) setError(error instanceof Error ? error.message : "Unable to review dates."); }
    finally { submitting.current = false; if (!current.signal.aborted) setBusy(false); }
  }
  async function assign(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current || !reviewed) return;
    submitting.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const result = await assignMenu(request, menu.id, reviewed, confirmed);
      setNotice(`Menu #${result.menu_id} assignment saved for ${result.service_dates.length} date(s). Current assignments are shown below.`);
      setReviewed(null); setConfirmed([]);
      const current = new AbortController(); controller.current = current;
      try { setReviewed(await inspectDates(request, dates, current.signal)); }
      catch { setError("Assignments were saved, but could not be refreshed. Review dates again to check the current state."); }
    } catch (error) {
      setReviewed(null); setConfirmed([]);
      setError(error instanceof ApiError && error.status === 409 ? "A date assignment changed. Review dates again before confirming replacements; nothing was overwritten by this request." :
        error instanceof ApiError && (error.status === 0 || error.status >= 500) ? "The assignment result could not be confirmed. Review dates again before submitting anything else." :
        error instanceof Error ? error.message : "Unable to assign menu.");
    } finally { submitting.current = false; setBusy(false); }
  }

  return <section className="panel"><h3>Assign saved menu #{menu.id} to dates</h3>
    <p className="muted">Only selected dates change. Existing orders keep their recorded menu and sale-time snapshots. Shared menu definitions are not edited.</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <form className="inline-form" onSubmit={e => { e.preventDefault(); try { setDates(addDate(dates, day)); setDay(""); invalidate(); } catch (error) { setError((error as Error).message); } }}>
      <label>Service date to add<input type="date" required value={day} disabled={busy} onChange={e => setDay(e.target.value)} /></label>
      <button type="submit" className="secondary" disabled={busy || !day || dates.length >= 366}>Add date</button></form>
    <ul className="date-chips" aria-label="Selected service dates">{dates.map(date => <li key={date}><span>{date}</span><button type="button" className="text-button" disabled={busy}
      onClick={() => { setDates(current => current.filter(value => value !== date)); invalidate(); }} aria-label={`Remove date ${date}`}>Remove</button></li>)}</ul>
    {!dates.length && <p className="muted">Add one or more dates across a week or month, then review their current assignments.</p>}
    <button type="button" className="secondary" disabled={busy || !dates.length} onClick={() => void review()}>{busy ? "Working…" : "Review date assignments"}</button>
    {reviewed && <form onSubmit={assign} className="schedule-review"><div className="table-scroll" role="region" aria-label="Menu assignment review" tabIndex={0}><table><caption>Review assignment to menu #{menu.id}</caption>
      <thead><tr><th scope="col">Service date</th><th scope="col">Current menu</th><th scope="col">Change / confirmation</th></tr></thead>
      <tbody>{reviewed.map(row => <tr key={row.service_date}><th scope="row">{row.service_date}</th><td>{row.expected_menu_id === null ? "Unassigned" : `#${row.expected_menu_id}${row.label ? ` · ${row.label}` : ""}`}</td><td>
        {needsReplacement(row, menu.id) ? <label className="check-label"><input type="checkbox" disabled={busy} checked={confirmed.includes(row.service_date)} onChange={e => setConfirmed(current => e.target.checked ? [...current, row.service_date] : current.filter(date => date !== row.service_date))} />
          Replace menu #{row.expected_menu_id} with #{menu.id} for {row.service_date}</label> : row.expected_menu_id === menu.id ? "Already assigned; no change" : `Assign menu #${menu.id}`}
      </td></tr>)}</tbody></table></div>
      <button type="submit" disabled={busy || reviewed.every(row => row.expected_menu_id === menu.id) || reviewed.some(row => needsReplacement(row, menu.id) && !confirmed.includes(row.service_date))}>Assign menu #{menu.id}</button></form>}
  </section>;
}
