"use client";

import { useEffect, useRef, useState } from "react";
import type { Employee, RequestApi, Visitor } from "@/lib/api";

export type Customer = { employee_number: string; name: string } | { visitor_id: number; name: string };

export default function CustomerPicker({ kind, request, selected, onSelect }: {
  kind: "employee" | "visitor"; request: RequestApi; selected: Customer | null; onSelect: (customer: Customer | null) => void;
}) {
  const [q, setQ] = useState("");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [visitors, setVisitors] = useState<Visitor[]>([]);
  const [searched, setSearched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newName, setNewName] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function search(event: React.FormEvent) {
    event.preventDefault(); controller.current?.abort();
    const current = new AbortController(); controller.current = current;
    setBusy(true); setError(""); setSearched(false); setEmployees([]); setVisitors([]);
    try {
      const path = `/api/${kind === "employee" ? "employees" : "visitors"}?q=${encodeURIComponent(q.trim())}&limit=20`;
      if (kind === "employee") setEmployees(await request<Employee[]>(path, { signal: current.signal }));
      else setVisitors(await request<Visitor[]>(path, { signal: current.signal }));
      setSearched(true);
    } catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) setError(error instanceof Error ? error.message : "Search failed.");
    } finally { if (!current.signal.aborted) setBusy(false); }
  }

  async function create(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const visitor = await request<Visitor>("/api/visitors", { method: "POST", body: { display_name: newName.trim() } });
      onSelect({ visitor_id: visitor.id, name: visitor.display_name }); setNewName(""); setVisitors([visitor]);
    } catch (error) { setError(error instanceof Error ? error.message : "Visitor creation failed."); }
    finally { setBusy(false); }
  }

  return <div className="customer-picker">
    <form onSubmit={search} className="inline-form"><label className="grow">{kind === "employee" ? "Employee number or name" : "Visitor name"}
      <input value={q} onChange={e => setQ(e.target.value)} maxLength={100} autoComplete="off" /></label>
      <button type="submit" disabled={busy}>{busy ? "Searching…" : "Search"}</button></form>
    {error && <p className="error" role="alert">{error}</p>}
    {selected && <p className="selected" role="status">Selected: <strong>{selected.name}</strong>{"employee_number" in selected ? ` · ${selected.employee_number}` : ` · Visitor #${selected.visitor_id}`}
      <button type="button" className="text-button" onClick={() => onSelect(null)}>Clear selection</button></p>}
    <ul className="search-results" aria-label="Customer search results">{kind === "employee" ? employees.map(employee => <li key={employee.employee_number}>
      <button type="button" className="result-button" onClick={() => onSelect({ employee_number: employee.employee_number, name: employee.full_name })}>
        <strong>{employee.full_name}</strong><span>{employee.employee_number}{employee.position ? ` · ${employee.position}` : ""}</span></button></li>) :
      visitors.map(visitor => <li key={visitor.id}><button type="button" className="result-button" onClick={() => onSelect({ visitor_id: visitor.id, name: visitor.display_name })}>
        <strong>{visitor.display_name}</strong><span>Visitor #{visitor.id}</span></button></li>)}</ul>
    {searched && !employees.length && !visitors.length && <p role="status" className="muted">No matches found.</p>}
    {searched && (employees.length === 20 || visitors.length === 20) && <p className="muted">Showing the first 20 matches. Refine your search if needed.</p>}
    {kind === "visitor" && <details><summary>Create a new visitor</summary><p className="muted">Search first to reuse an existing visitor. Matching names can belong to different people.</p>
      <form onSubmit={create} className="inline-form"><label className="grow">Visitor display name<input value={newName} onChange={e => setNewName(e.target.value)} required maxLength={200} /></label>
        <button type="submit" disabled={busy || !newName.trim()}>Create and select</button></form></details>}
  </div>;
}
