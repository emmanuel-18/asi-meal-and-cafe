"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ApiError, type RequestApi, type Visitor } from "@/lib/api";
import { scheduleCustomerSearch, suggestionKey, type CustomerResult, type Customer } from "@/lib/customer-search";

export type { Customer } from "@/lib/customer-search";

export default function CustomerPicker({ kind, request, selected, onSelect }: {
  kind: "employee" | "visitor"; request: RequestApi; selected: Customer | null; onSelect: (customer: Customer | null) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<CustomerResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);
  const [createUncertain, setCreateUncertain] = useState(false);
  const [newName, setNewName] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [retry, setRetry] = useState(0);
  const id = useId();
  const cancelSearch = useRef<(() => void) | null>(null);
  const creatingRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const clearRef = useRef<HTMLButtonElement>(null);
  const term = q.trim();

  useEffect(() => {
    if (!term) return;
    const cancel = scheduleCustomerSearch(kind, term, request, rows => { setResults(rows); setSearched(true); },
      error => setSearchError(error instanceof Error ? error.message : "Search failed."), () => setSearching(false));
    cancelSearch.current = cancel;
    return cancel;
  }, [term, kind, request, retry]);

  function changeQuery(value: string) {
    if (value.trim() !== term) {
      cancelSearch.current?.();
      setResults([]); setSearched(false); setSearchError(""); setSearching(!!value.trim()); setActive(-1);
    }
    if (selected) onSelect(null);
    setQ(value); setOpen(true);
  }
  function choose(result: CustomerResult) {
    cancelSearch.current?.();
    onSelect(result.customer); setQ(""); setResults([]); setSearched(false); setSearching(false); setSearchError(""); setOpen(false); setActive(-1);
    requestAnimationFrame(() => clearRef.current?.focus());
  }
  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (creatingRef.current || createUncertain) return;
    creatingRef.current = true; setCreating(true); setCreateError("");
    try {
      const visitor = await request<Visitor>("/api/visitors", { method: "POST", body: { display_name: newName.trim() } });
      choose({ customer: { visitor_id: visitor.id, name: visitor.display_name }, detail: `Visitor #${visitor.id}` }); setNewName("");
    } catch (error) {
      if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
        setCreateUncertain(true); setCreateError("Creation could not be confirmed. Search for the visitor and review the results before trying again.");
      } else setCreateError(error instanceof Error ? error.message : "Visitor creation failed.");
    }
    finally { creatingRef.current = false; setCreating(false); }
  }

  return <div className="customer-picker">
    {selected ? <p className="selected" role="status">Selected: <strong>{selected.name}</strong>{"employee_number" in selected ? ` · ${selected.employee_number}` : ` · Visitor #${selected.visitor_id}`}
      <button type="button" className="text-button" ref={clearRef} onClick={() => { onSelect(null); requestAnimationFrame(() => inputRef.current?.focus()); }}>Clear selection</button></p> : <div className="customer-search">
      <label htmlFor={`${id}-input`}>{kind === "employee" ? "Employee number or name" : "Visitor name"}</label>
      <div className="customer-search-field"><input id={`${id}-input`} ref={inputRef} value={q} onChange={e => changeQuery(e.target.value)} maxLength={100} autoComplete="off"
        role="combobox" aria-autocomplete="list" aria-expanded={open && results.length > 0} aria-controls={`${id}-list`}
        aria-activedescendant={open && active >= 0 && active < results.length ? `${id}-option-${active}` : undefined}
        onFocus={() => setOpen(true)} onBlur={() => { setOpen(false); setActive(-1); }} onKeyDown={e => {
          const action = suggestionKey(e.key, active, results.length, open);
          if (action.action === "move") { e.preventDefault(); setOpen(true); setActive(action.index);
            requestAnimationFrame(() => document.getElementById(`${id}-option-${action.index}`)?.scrollIntoView({ block: "nearest" })); }
          else if (action.action === "select") { e.preventDefault(); choose(results[action.index]); }
          else if (action.action === "close") { setOpen(false); setActive(-1); }
        }} />
      {open && results.length > 0 && <ul className="customer-suggestions" id={`${id}-list`} role="listbox" aria-label="Customer suggestions">{results.map((result, index) =>
        <li id={`${id}-option-${index}`} role="option" aria-selected={index === active} key={"employee_number" in result.customer ? result.customer.employee_number : result.customer.visitor_id}
          onMouseDown={e => e.preventDefault()} onClick={() => choose(result)}><strong>{result.customer.name}</strong><span>{result.detail}</span></li>)}</ul>}</div>
      <p className="search-status muted" role="status">{searching ? "Searching…" : searched && !results.length ? "No matches found." : searched && results.length === 20 ? "Showing the first 20 matches. Refine your search if needed." : searched ? `${results.length} suggestions available.` : ""}</p>
      {searchError && <p className="error" role="alert">{searchError} <button type="button" className="text-button" onClick={() => { setSearchError(""); setSearching(true); setOpen(true); setRetry(value => value + 1); inputRef.current?.focus(); }}>Retry search</button></p>}
    </div>}
    {kind === "visitor" && <details><summary>Create a new visitor</summary><p className="muted">Search first to reuse an existing visitor. Matching names can belong to different people.</p>
      <form onSubmit={create} className="inline-form"><label className="grow">Visitor display name<input value={newName} onChange={e => setNewName(e.target.value)} required maxLength={200} /></label>
        <button type="submit" disabled={creating || createUncertain || !newName.trim()}>{creating ? "Creating…" : "Create and select"}</button></form>
      {createError && <p className="error" role="alert">{createError}</p>}
      {createUncertain && <button type="button" className="secondary" onClick={() => { setCreateUncertain(false); setNewName(""); setCreateError(""); }}>I have reviewed the search results</button>}</details>}
  </div>;
}
