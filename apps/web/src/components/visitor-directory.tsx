"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type RequestApi, type Visitor } from "@/lib/api";

export default function VisitorDirectory({ request }: { request: RequestApi }) {
  const [query, setQuery] = useState(""); const [search, setSearch] = useState("");
  const [page, setPage] = useState(0); const [revision, setRevision] = useState(0);
  const [rows, setRows] = useState<Visitor[]>([]); const [loading, setLoading] = useState(true);
  const [name, setName] = useState(""); const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const submitting = useRef(false);
  const [edit, setEdit] = useState<Visitor | null>(null); const [editName, setEditName] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ q: search, limit: "20", offset: String(page * 20) });
    void request<Visitor[]>(`/api/visitors?${params}`, { signal: controller.signal }).then(setRows).catch(error => {
      if (!controller.signal.aborted) { setRows([]); setError(error instanceof Error ? error.message : "Unable to search visitors."); }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [request, search, page, revision]);
  async function create(event: React.FormEvent) {
    event.preventDefault(); if (submitting.current || uncertain || !name.trim()) return;
    submitting.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const visitor = await request<Visitor>("/api/visitors", { method: "POST", body: { display_name: name.trim() } });
      setNotice(`Visitor #${visitor.id} created. Search by name to review.`); setName(""); setPage(0); setLoading(true); setRevision(v => v + 1);
    } catch (error) {
      if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
        setUncertain(true); setError("Creation could not be confirmed. Search for the visitor and review the results before trying again.");
      } else setError(error instanceof Error ? error.message : "Unable to create visitor.");
    } finally { submitting.current = false; setBusy(false); }
  }
  async function change(visitor: Visitor, remove: boolean) {
    if (submitting.current || uncertain) return;
    if (remove && !window.confirm(`Permanently delete visitor #${visitor.id}? Visitors used by orders cannot be deleted.`)) return;
    if (!remove && !editName.trim()) { setError("Enter a visitor name."); return; }
    submitting.current = true; setBusy(true); setError(""); setNotice("");
    try {
      await request(`/api/visitors/${visitor.id}`, { method: remove ? "DELETE" : "PATCH", body: remove ? { expected_name: visitor.display_name } : { expected_name: visitor.display_name, display_name: editName.trim() } });
      setEdit(null); setNotice(remove ? "Visitor deleted." : "Visitor updated. Existing order details remain unchanged."); setLoading(true); setRevision(v => v + 1);
    } catch (error) {
      if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) { setUncertain(true); setError("The change could not be confirmed. Search and review the visitor before trying again."); }
      else setError(error instanceof Error ? error.message : "Unable to change visitor.");
    } finally { submitting.current = false; setBusy(false); }
  }
  return <><div className="section-heading"><div><h2>Visitors</h2><p className="muted">Search and register visitors. Names do not uniquely identify a person.</p></div></div>
    <section className="panel"><h3>Visitor directory</h3><form className="filter-row" onSubmit={event => { event.preventDefault(); setError(""); setLoading(true); setPage(0); setSearch(query.trim()); setRevision(v => v + 1); }}>
      <label className="grow">Visitor name<input value={query} maxLength={100} onChange={event => setQuery(event.target.value)} /></label><button type="submit" disabled={loading}>Search</button></form>
      {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
      {loading ? <p role="status">Loading visitors...</p> : !rows.length ? <p role="status">No visitors found on this page.</p> : <div className="table-scroll" role="region" aria-label="Visitor search results" tabIndex={0}><table><thead><tr><th scope="col">Visitor ID</th><th scope="col">Name</th><th scope="col">Edit or delete</th></tr></thead><tbody>{rows.map(visitor => <tr key={visitor.id}><th scope="row">#{visitor.id}</th><td>{visitor.display_name}</td><td><div className="button-row"><button type="button" className="icon-button" disabled={busy || uncertain} aria-label={`Edit visitor ${visitor.display_name} number ${visitor.id}`} title="Edit visitor" onClick={() => { setEdit(visitor); setEditName(visitor.display_name); }}>✎</button><button type="button" className="icon-button" disabled={busy || uncertain} aria-label={`Delete visitor ${visitor.display_name} number ${visitor.id}`} title="Delete visitor" onClick={() => void change(visitor, true)}>×</button></div></td></tr>)}</tbody></table></div>}
      {edit && <form className="inline-form" onSubmit={event => { event.preventDefault(); void change(edit, false); }}><label>Visitor display name<input value={editName} required maxLength={200} onChange={event => setEditName(event.target.value)} /></label><button disabled={busy || uncertain}>Save changes</button><button type="button" className="secondary" disabled={busy} onClick={() => setEdit(null)}>Cancel</button></form>}
      <div className="pagination"><button className="secondary" disabled={loading || page === 0} onClick={() => { setLoading(true); setPage(v => v - 1); }}>Previous</button><span>Page {page + 1}</span><button className="secondary" disabled={loading || rows.length < 20 || page >= 500} onClick={() => { setLoading(true); setPage(v => v + 1); }}>Next</button></div>
    </section><section className="panel"><h3>Add Visitor</h3><p className="muted">Search first; people can share a name.</p><form className="inline-form" onSubmit={create}>
      <label className="grow">Visitor display name<input value={name} maxLength={200} required onChange={event => setName(event.target.value)} /></label><button disabled={busy || uncertain || !name.trim()}>{busy ? "Creating..." : "Add Visitor"}</button></form>
      {uncertain && <button type="button" className="secondary" onClick={() => { setUncertain(false); setName(""); setError(""); setNotice("Review the search results before entering another visitor."); }}>I have reviewed the directory</button>}
    </section></>;
}
