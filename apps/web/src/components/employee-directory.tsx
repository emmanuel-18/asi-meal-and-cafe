"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type Employee, type RequestApi, type Role } from "@/lib/api";
import { canImport, fileError, fileErrorMessage, issueMessage, pageSize, searchEmployees, submitImport, type ImportResult } from "@/lib/employees";

export default function EmployeeDirectory({ request, role }: { request: RequestApi; role: Role }) {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [rows, setRows] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const submitting = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    void searchEmployees(request, search, page, controller.signal).then(setRows).catch(error => {
      if (!(error instanceof Error && error.name === "AbortError")) { setRows([]); setError(error instanceof Error ? error.message : "Unable to search employees."); }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [request, search, page, revision]);

  function reload() { setError(""); setLoading(true); setRevision(value => value + 1); }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current || !canImport(role)) return;
    const invalid = fileError(file);
    if (invalid || !file) { setImportError(invalid); return; }
    setImporting(true); setImportError(""); setResult(null);
    try {
      const outcome = await submitImport(request, file, submitting, () => { setPage(0); reload(); });
      setResult(outcome);
    } catch (error) {
      setImportError(error instanceof ApiError && (error.status === 0 || error.status >= 500)
        ? "The import outcome could not be confirmed. Review the directory before deliberately importing again."
        : error instanceof Error ? error.message : "Unable to import the file.");
    } finally { setImporting(false); }
  }

  return <><div className="section-heading"><div><h2>Employees</h2><p className="muted">Search employee details imported from HRMS.</p></div></div>
    <section className="panel"><h3>Employee directory</h3>
      <form className="filter-row" onSubmit={event => { event.preventDefault(); setError(""); setLoading(true); setPage(0); setSearch(query.trim()); setRevision(value => value + 1); }}>
        <label className="grow">Employee number or name<input value={query} onChange={event => setQuery(event.target.value)} maxLength={100} /></label>
        <button type="submit" disabled={loading}>Search</button>
      </form>
      {error && <p className="error" role="alert">{error} <button type="button" className="text-button" onClick={reload}>Retry</button></p>}
      {loading ? <p role="status">Loading employees…</p> : !error && !rows.length ? <p role="status" className="muted">No employees found on this page.</p> : !error && <div className="table-scroll" role="region" aria-label="Employee directory search results" tabIndex={0}><table>
        <caption className="sr-only">Employee directory search results</caption><thead><tr><th scope="col">Employee number</th><th scope="col">Name</th><th scope="col">Position</th><th scope="col">Campaign</th><th scope="col">Line of business</th></tr></thead>
        <tbody>{rows.map(employee => <tr key={employee.employee_number}><th scope="row">{employee.employee_number}</th><td>{employee.full_name}</td><td>{employee.position || "—"}</td><td>{employee.campaign || "—"}</td><td>{employee.line_of_business || "—"}</td></tr>)}</tbody>
      </table></div>}
      <div className="pagination"><button type="button" className="secondary" disabled={loading || page === 0} onClick={() => { setError(""); setLoading(true); setPage(value => value - 1); }}>Previous</button><span>Page {page + 1}</span>
        <button type="button" className="secondary" disabled={loading || !!error || rows.length < pageSize || page >= 500} onClick={() => { setError(""); setLoading(true); setPage(value => value + 1); }}>Next</button></div>
      {page >= 500 && <p className="muted">Refine the search to see more results.</p>}
    </section>
    {canImport(role) && <section className="panel import-panel"><h3>Import HRMS CSV <span className="admin-label">Admin only</span></h3>
      <p className="muted">Choose an HRMS export and submit it explicitly. Invalid files are rejected without partial employee updates.</p>
      <form className="inline-form" onSubmit={submit}><label className="grow">CSV file<input type="file" accept=".csv,text/csv" disabled={importing} onChange={event => { setFile(event.target.files?.[0] ?? null); setImportError(""); setResult(null); }} /></label>
        <button type="submit" disabled={importing || !file}>{importing ? "Importing…" : "Import employees"}</button></form>
      {file && <p className="muted">Selected: {file.name} ({file.size.toLocaleString()} bytes; maximum 8 MiB)</p>}
      {importError && <p className="error" role="alert">{importError}</p>}
      {result && <div className={result.status === "completed" ? "notice" : "error"} role="status"><strong>Import #{result.import_id}: {result.status === "completed" ? "Completed" : "Failed"}</strong>
        <p>Inserted: {result.inserted_rows} · Updated: {result.updated_rows} · Unchanged: {result.unchanged_rows} · Rejected: {result.rejected_rows}</p>
        {result.status === "failed" && <><p>{fileErrorMessage(result.file_error_code)} No employee changes were applied.</p>
          {result.total_rows === 0 && <p>Record count unavailable.</p>}
          <ul>{result.errors.filter(row => Number.isSafeInteger(row?.row_number) && row.row_number > 0 && Array.isArray(row.issues)).map(row => <li key={row.row_number}>Record {row.row_number}: {row.issues.map(issueMessage).join(" ")}</li>)}</ul>
          {result.errors_truncated && <p>Additional record errors were omitted.</p>}</>}
      </div>}
    </section>}
  </>;
}
