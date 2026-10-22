"use client";
import { useCallback, useEffect, useState } from "react";
import type { RequestApi } from "@/lib/api";

type Account = { id: number; login_name: string; display_name: string; role: string; is_enabled: boolean; password_change_required: boolean; updated_at: string };

export default function UsersWorkspace({ request }: { request: RequestApi }) {
  const [rows, setRows] = useState<Account[]>([]); const [q, setQ] = useState("");
  const [search, setSearch] = useState(""); const [page, setPage] = useState(0);
  const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const load = useCallback(async () => {
    try { setRows(await request<Account[]>(`/api/users?q=${encodeURIComponent(search)}&limit=20&offset=${page * 20}`)); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Unable to load accounts."); }
  }, [request, search, page]);
  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = e.currentTarget; const data = new FormData(form); setBusy(true); setMessage("");
    try { await request("/api/users", { method: "POST", body: { login_name: data.get("login"), display_name: data.get("display"), role: data.get("role"), temporary_password: data.get("password") } }); form.reset(); setMessage("Account created. Share the temporary password privately."); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Unable to create account."); }
    finally { (form.elements.namedItem("password") as HTMLInputElement).value = ""; setBusy(false); }
  }
  async function edit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (!editing) return; const form = e.currentTarget; const data = new FormData(form);
    if (!window.confirm("Save this account change? Role, status, and password changes revoke existing sessions.")) return;
    setBusy(true); setMessage("");
    try { await request(`/api/users/${editing.id}`, { method: "PATCH", body: { expected_updated_at: editing.updated_at, display_name: data.get("display"), role: data.get("role"), is_enabled: data.get("enabled") === "yes", ...(data.get("password") ? { temporary_password: data.get("password") } : {}) } }); setEditing(null); setMessage("Account updated."); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Unable to update account."); }
    finally { (form.elements.namedItem("password") as HTMLInputElement).value = ""; setBusy(false); }
  }
  return <section><h2>Users</h2><p className="muted">Manage individual accounts. Share temporary passwords privately.</p>
    {message && <p role="status">{message}</p>}
    <form onSubmit={e => { e.preventDefault(); setPage(0); setSearch(q); }} className="button-row"><label>Search accounts<input value={q} onChange={e => setQ(e.target.value)} maxLength={100}/></label><button>Search</button></form>
    <div className="table-scroll" role="region" aria-label="User accounts" tabIndex={0}><table><thead><tr><th>Login</th><th>Name</th><th>Role</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td>{row.login_name}</td><td>{row.display_name}</td><td>{row.role.replaceAll("_", " ")}</td><td>{row.is_enabled ? "Active" : "Disabled"}{row.password_change_required ? ", password change required" : ""}</td><td>{row.role !== "super_admin" && <button className="secondary" type="button" onClick={() => setEditing(row)}>Edit</button>}</td></tr>)}</tbody></table></div>
    <div className="button-row"><button className="secondary" disabled={!page} onClick={() => setPage(p => p - 1)}>Previous</button><span>Page {page + 1}</span><button className="secondary" disabled={rows.length < 20} onClick={() => setPage(p => p + 1)}>Next</button></div>
    {editing && <form className="panel" key={editing.id} onSubmit={edit}><h3>Edit {editing.login_name}</h3><label>Display name<input name="display" required maxLength={255} defaultValue={editing.display_name}/></label><label>Role<select name="role" defaultValue={editing.role}><option value="admin">Admin</option><option value="assistant_admin">Assistant Admin</option></select></label><label>Status<select name="enabled" defaultValue={editing.is_enabled ? "yes" : "no"}><option value="yes">Active</option><option value="no">Disabled</option></select></label><label>New temporary password (optional)<input name="password" type="password" autoComplete="new-password" minLength={8}/></label><div className="button-row"><button disabled={busy}>Save changes</button><button type="button" className="secondary" onClick={() => setEditing(null)}>Cancel</button></div></form>}
    <details className="panel"><summary>Create account</summary><form onSubmit={create}><label>Login name<input name="login" required maxLength={255} autoComplete="off"/></label><label>Display name<input name="display" required maxLength={255}/></label><label>Role<select name="role"><option value="assistant_admin">Assistant Admin</option><option value="admin">Admin</option></select></label><label>Temporary password<input name="password" type="password" required minLength={8} autoComplete="new-password"/></label><button disabled={busy}>Create account</button></form></details>
  </section>;
}
