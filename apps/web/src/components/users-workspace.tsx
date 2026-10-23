"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RequestApi } from "@/lib/api";

type Account = {
  id: number;
  login_name: string;
  display_name: string;
  role: string;
  is_enabled: boolean;
  password_change_required: boolean;
  updated_at: string;
};

function roleLabel(role: string) {
  return ({ super_admin: "Super Admin", admin: "Admin", assistant_admin: "Assistant Admin" } as Record<string, string>)[role]
    ?? role.replaceAll("_", " ");
}

function AccountIcon({ kind }: { kind: "add" | "search" | "edit" }) {
  const paths = {
    add: <><circle cx="9" cy="8" r="3.2" /><path d="M3.5 20v-1.5a5.5 5.5 0 0 1 11 0V20M18 8v7m-3.5-3.5h7" /></>,
    search: <><circle cx="10.8" cy="10.8" r="6.6" /><path d="m16 16 4.5 4.5" /></>,
    edit: <><path d="m4 16-.8 4.8L8 20l10.8-10.8-4-4L4 16z" /><path d="m12.8 7.2 4 4" /></>,
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {paths[kind]}
  </svg>;
}

function AccountStatus({ account }: { account: Account }) {
  return <div className="users-status-list">
    <span className={`users-status users-status--${account.is_enabled ? "active" : "disabled"}`}>
      <span aria-hidden="true" />
      {account.is_enabled ? "Active" : "Disabled"}
    </span>
    {account.password_change_required && <span className="users-password-status">Password change required</span>}
  </div>;
}

export default function UsersWorkspace({ request }: { request: RequestApi }) {
  const [rows, setRows] = useState<Account[]>([]);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const createTrigger = useRef<HTMLButtonElement>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const accounts = await request<Account[]>(
        `/api/users?q=${encodeURIComponent(search)}&limit=20&offset=${page * 20}`,
        signal ? { signal } : undefined,
      );
      if (!signal?.aborted) setRows(accounts);
    } catch (error) {
      if (signal?.aborted) return;
      setRows([]);
      setLoadError(error instanceof Error ? error.message : "Unable to load accounts.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [request, search, page]);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => load(controller.signal));
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if ((creating || editing) && !element.open) {
      element.showModal();
      element.querySelector<HTMLElement>("[data-dialog-autofocus]")?.focus();
    } else if (!creating && !editing && element.open) element.close();
  }, [creating, editing]);

  function openCreate() {
    setActionError("");
    setSuccess("");
    setEditing(null);
    setCreating(true);
  }

  function closeEditor() {
    if (busy) return;
    if (dialog.current?.open) dialog.current.close();
    setCreating(false);
    setEditing(null);
  }

  function searchAccounts(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextSearch = q.trim();
    setActionError("");
    setSuccess("");
    if (nextSearch === search && page === 0) return;
    setLoading(true);
    setLoadError("");
    setPage(0);
    setSearch(nextSearch);
  }

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setActionError("");
    setSuccess("");
    try {
      await request("/api/users", {
        method: "POST",
        body: {
          login_name: data.get("login"),
          display_name: data.get("display"),
          role: data.get("role"),
          temporary_password: data.get("password"),
        },
      });
      form.reset();
      setCreating(false);
      setSuccess("Account created. Share the temporary password privately.");
      setLoading(true);
      setLoadError("");
      await load();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to create account.");
    } finally {
      const password = form.elements.namedItem("password") as HTMLInputElement | null;
      if (password) password.value = "";
      setBusy(false);
    }
  }

  async function edit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = String(data.get("password") ?? "");
    const changes = [
      String(data.get("display")) !== editing.display_name && "display name",
      String(data.get("role")) !== editing.role && "role",
      (data.get("enabled") === "yes") !== editing.is_enabled && "account status",
      password && "temporary password",
    ].filter(Boolean);
    const changeSummary = changes.length ? changes.join(", ") : "no field changes";
    if (!window.confirm(`Save ${changeSummary} for ${editing.login_name}? Role, status, or password changes revoke existing sessions.`)) return;
    setBusy(true);
    setActionError("");
    setSuccess("");
    try {
      await request(`/api/users/${editing.id}`, {
        method: "PATCH",
        body: {
          expected_updated_at: editing.updated_at,
          display_name: data.get("display"),
          role: data.get("role"),
          is_enabled: data.get("enabled") === "yes",
          ...(password ? { temporary_password: password } : {}),
        },
      });
      setEditing(null);
      setSuccess("Account updated.");
      setLoading(true);
      setLoadError("");
      await load();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to update account.");
    } finally {
      const passwordInput = form.elements.namedItem("password") as HTMLInputElement | null;
      if (passwordInput) passwordInput.value = "";
      setBusy(false);
    }
  }

  function editButton(account: Account) {
    if (account.role === "super_admin") {
      return <span className="users-protected-label">Protected account</span>;
    }
    return <button type="button" className="users-edit-button" onClick={() => {
      setActionError("");
      setSuccess("");
      setEditing(account);
      setCreating(false);
    }}>
      <AccountIcon kind="edit" />Edit
    </button>;
  }

  return <section className="users-workspace" aria-labelledby="users-heading">
    <header className="users-page-header">
      <div className="users-page-heading">
        <span className="users-eyebrow"><span aria-hidden="true" /> ACCESS &amp; GOVERNANCE</span>
        <h2 id="users-heading">Users</h2>
        <p>Manage individual accounts and their access.</p>
      </div>
      <button ref={createTrigger} type="button" className="users-create-button" onClick={openCreate}>
        <AccountIcon kind="add" />Create user
      </button>
    </header>

    <p className="users-context">Temporary passwords must be shared privately. Account changes may revoke active sessions.</p>

    {actionError && <p className="users-feedback users-feedback--error" role="alert">{actionError}</p>}
    {success && <p className="users-feedback users-feedback--success" role="status">{success}</p>}

    <form className="users-toolbar" onSubmit={searchAccounts} aria-label="Search user accounts">
      <div className="users-toolbar-label">
        <span className="users-toolbar-icon" aria-hidden="true"><AccountIcon kind="search" /></span>
        <div><h3>Account directory</h3><p>Search by login or display name</p></div>
      </div>
      <label className="users-search-field">
        <span>Search accounts</span>
        <input value={q} onChange={event => setQ(event.target.value)} maxLength={100} placeholder="Enter a login or name" />
      </label>
      <button type="submit" className="users-search-button"><AccountIcon kind="search" />Search</button>
    </form>

    {loadError && <p className="users-feedback users-feedback--error" role="alert">
      <span>{loadError}</span>
      <button type="button" className="secondary" onClick={() => { setLoading(true); setLoadError(""); void load(); }}>Retry</button>
    </p>}
    {loading && <div className="users-state" role="status"><span className="users-state-mark" aria-hidden="true" />Loading accounts…</div>}
    {!loading && !loadError && !rows.length && <div className="users-state users-state--empty" role="status">
      <span className="users-empty-mark" aria-hidden="true"><AccountIcon kind="search" /></span>
      <strong>{search ? "No accounts match this search" : "No accounts to display"}</strong>
      <span>{search ? "Try another login or display name." : "Account results will appear here."}</span>
    </div>}

    {!loading && !loadError && !!rows.length && <>
      <div className="users-table-scroll" role="region" aria-label="User accounts" tabIndex={0}>
        <table className="users-table">
          <caption className="sr-only">User accounts</caption>
          <colgroup><col className="users-column-login" /><col className="users-column-name" /><col className="users-column-role" /><col className="users-column-status" /><col className="users-column-action" /></colgroup>
          <thead><tr><th scope="col">Login</th><th scope="col">Display name</th><th scope="col">Role</th><th scope="col">Account status</th><th scope="col">Action</th></tr></thead>
          <tbody>{rows.map(account => <tr key={account.id}>
            <td className="users-login">{account.login_name}</td>
            <td className="users-name">{account.display_name}</td>
            <td><span className={`users-role users-role--${account.role}`}>{roleLabel(account.role)}</span></td>
            <td><AccountStatus account={account} /></td>
            <td className="users-actions-cell">{editButton(account)}</td>
          </tr>)}</tbody>
        </table>
      </div>

      <ul className="users-mobile-list" aria-label="User accounts">
        {rows.map(account => <li key={account.id} className="users-mobile-row">
          <div className="users-mobile-identity">
            <strong>{account.login_name}</strong>
            <span>{account.display_name}</span>
          </div>
          <dl className="users-mobile-meta">
            <div><dt>Role</dt><dd><span className={`users-role users-role--${account.role}`}>{roleLabel(account.role)}</span></dd></div>
            <div><dt>Account status</dt><dd><AccountStatus account={account} /></dd></div>
          </dl>
          <div className="users-mobile-actions">{editButton(account)}</div>
        </li>)}
      </ul>

      <nav className="users-pagination" aria-label="User account pages">
        <button type="button" className="secondary" disabled={!page || loading} onClick={() => { setLoading(true); setPage(current => current - 1); }}>
          <span aria-hidden="true">←</span>Previous
        </button>
        <span aria-current="page">Page {page + 1}</span>
        <button type="button" className="secondary" disabled={rows.length < 20 || loading} onClick={() => { setLoading(true); setPage(current => current + 1); }}>
          Next<span aria-hidden="true">→</span>
        </button>
      </nav>
    </>}

    <dialog
      ref={dialog}
      className="users-dialog"
      aria-labelledby="users-dialog-title"
      aria-describedby="users-dialog-description"
      onCancel={event => { if (busy) event.preventDefault(); }}
      onKeyDown={event => {
        if (event.key === "Escape" && !busy) {
          event.preventDefault();
          closeEditor();
        }
      }}
      onClose={() => { setCreating(false); setEditing(null); }}
    >
      <div className="users-dialog-header">
        <div>
          <span className="users-dialog-kicker">{creating ? "NEW ACCOUNT" : "ACCOUNT SETTINGS"}</span>
          <h3 id="users-dialog-title">{creating ? "Create user" : editing ? `Edit ${editing.login_name}` : "Account settings"}</h3>
          <p id="users-dialog-description">
            {creating ? "Create an individual Admin or Assistant Admin account." : "Review the account fields before confirming changes."}
          </p>
        </div>
        <button type="button" className="users-dialog-close" aria-label="Close account form" disabled={busy} onClick={closeEditor}>×</button>
      </div>

      {creating && <form className="users-form" onSubmit={create} aria-label="Create account">
        <div className="users-form-grid">
          <label>Login name<input autoFocus data-dialog-autofocus name="login" required maxLength={255} autoComplete="off" /></label>
          <label>Display name<input name="display" required maxLength={255} autoComplete="name" /></label>
          <div className="users-form-field">
            <label htmlFor="users-create-role">Role</label>
            <select id="users-create-role" name="role" defaultValue="assistant_admin" aria-describedby="users-create-role-help"><option value="assistant_admin">Assistant Admin</option><option value="admin">Admin</option></select>
            <span id="users-create-role-help" className="users-field-help">Super Admin access cannot be assigned here.</span>
          </div>
          <div className="users-form-field">
            <label htmlFor="users-create-password">Temporary password</label>
            <input id="users-create-password" name="password" type="password" required minLength={8} autoComplete="new-password" aria-describedby="users-create-password-help" />
            <span id="users-create-password-help" className="users-field-help">The user will be asked to change this password at first sign-in.</span>
          </div>
        </div>
        <div className="users-dialog-actions">
          <button type="button" className="secondary" disabled={busy} onClick={closeEditor}>Cancel</button>
          <button type="submit" disabled={busy}>{busy ? "Creating account…" : "Create account"}</button>
        </div>
      </form>}

      {editing && <form className="users-form" key={editing.id} onSubmit={edit} aria-label={`Edit account ${editing.login_name}`}>
        <label>Display name<input autoFocus data-dialog-autofocus name="display" required maxLength={255} defaultValue={editing.display_name} autoComplete="name" /></label>
        <div className="users-form-grid">
          <div className="users-form-field">
            <label htmlFor="users-edit-role">Role</label>
            <select id="users-edit-role" name="role" defaultValue={editing.role} aria-describedby="users-edit-role-help"><option value="admin">Admin</option><option value="assistant_admin">Assistant Admin</option></select>
            <span id="users-edit-role-help" className="users-field-help">Role changes revoke existing sessions.</span>
          </div>
          <div className="users-form-field">
            <label htmlFor="users-edit-enabled">Account status</label>
            <select id="users-edit-enabled" name="enabled" defaultValue={editing.is_enabled ? "yes" : "no"} aria-describedby="users-edit-enabled-help"><option value="yes">Active</option><option value="no">Disabled</option></select>
            <span id="users-edit-enabled-help" className="users-field-help">Disabling an account revokes its active sessions.</span>
          </div>
        </div>
        <div className="users-form-field">
          <label htmlFor="users-edit-password">New temporary password <span className="users-optional">(optional)</span></label>
          <input id="users-edit-password" name="password" type="password" minLength={8} autoComplete="new-password" aria-describedby="users-edit-password-help" />
          <span id="users-edit-password-help" className="users-field-help">Leave blank to keep the current password. Password changes revoke existing sessions.</span>
        </div>
        <div className="users-dialog-actions">
          <button type="button" className="secondary" disabled={busy} onClick={closeEditor}>Cancel</button>
          <button type="submit" disabled={busy}>{busy ? "Saving changes…" : "Save changes"}</button>
        </div>
      </form>}
    </dialog>
  </section>;
}
