"use client";

import { useEffect, useState } from "react";
import type { RequestApi } from "@/lib/api";

type SafeValue = string | number | boolean | null;
type Entry = {
  id: number;
  occurred_at: string;
  actor_id: number;
  actor_display_name: string;
  action: string;
  entity_type: string | null;
  reference: string | null;
  before: Record<string, SafeValue>;
  after: Record<string, SafeValue>;
  reason: string | null;
  local_operator?: string;
};
type Page = { items: Entry[]; next_cursor: string | null };
type IconKind = "order" | "edit" | "received" | "reversed" | "menu" | "dish" | "visitor"
  | "import" | "user" | "role" | "disabled" | "enabled" | "password" | "admin" | "auth" | "neutral";

const labels: Record<string, string> = {
  order_created: "Order created",
  order_edited: "Pending order edited",
  received_marked: "Marked Received",
  received_reversed: "Received reversed",
  menu_created: "Menu created",
  menu_date_assigned: "Menu assigned",
  dish_created: "Dish created",
  dish_updated: "Dish updated",
  dish_deactivated: "Dish deactivated",
  dish_deleted: "Dish deleted",
  visitor_created: "Visitor created",
  visitor_updated: "Visitor updated",
  visitor_deleted: "Visitor deleted",
  employee_import_inserted: "Employee inserted",
  employee_import_updated: "Employee updated",
  employee_import_completed: "Import completed",
  employee_import_failed: "Import failed",
  user_created: "User created",
  user_updated: "User updated",
  user_role_changed: "Role changed",
  user_disabled: "Account disabled",
  user_reactivated: "Account reactivated",
  user_password_reset: "Password reset",
  password_changed: "Password changed",
  super_admin_promoted: "Super Admin promoted",
  super_admin_recovered: "Super Admin access recovered",
  first_admin_provisioned: "First Admin provisioned",
  auth_login: "Signed in",
  auth_logout: "Signed out",
};

const iconPaths: Record<IconKind, React.ReactNode> = {
  order: <><path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" /><path d="M9 8h6M9 12h6" /></>,
  edit: <><path d="m4 16-.8 4.8L8 20l10.8-10.8-4-4L4 16z" /><path d="m12.8 7.2 4 4" /></>,
  received: <><path d="m5 12 4 4L19 6" /><circle cx="12" cy="12" r="9" /></>,
  reversed: <><path d="M4 8V3m0 5h5M4.8 8a8 8 0 1 1-.3 8" /><path d="m9 12-3 3 3 3" /></>,
  menu: <><path d="M5 3h14v18H5zM5 8h14M9 11h6" /><path d="M9 15h2" /></>,
  dish: <><path d="M4 13h16a8 8 0 0 1-16 0zM3 10h18" /><path d="M12 4v3m-4-2 1 2m7-2-1 2" /></>,
  visitor: <><circle cx="12" cy="8" r="3.5" /><path d="M4 21a8 8 0 0 1 16 0M18 5v6m-3-3h6" /></>,
  import: <><path d="M12 15V3m-5 5 5-5 5 5" /><path d="M4 14v6h16v-6" /></>,
  user: <><circle cx="12" cy="8" r="3.5" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  role: <><path d="M12 3 20 6v5c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6z" /><path d="m9 12 2 2 4-4" /></>,
  disabled: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3" /></>,
  enabled: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0m-4 7v3" /></>,
  password: <><circle cx="8" cy="15" r="4" /><path d="m11 12 8-8m-3 3 3 3m-6-1 3 3" /></>,
  admin: <><path d="M12 3 20 6v5c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6z" /><path d="M12 8v5m0 3h.01" /></>,
  auth: <><path d="M10 4H5v16h5m4-12 4 4-4 4m4-4H9" /></>,
  neutral: <><path d="M6 3h12v18H6z" /><path d="M9 8h6m-6 4h6m-6 4h4" /></>,
};

function iconKind(action: string): IconKind {
  if (action === "order_created") return "order";
  if (action === "order_edited") return "edit";
  if (action === "received_marked") return "received";
  if (action === "received_reversed") return "reversed";
  if (action.startsWith("menu_")) return "menu";
  if (action.startsWith("dish_")) return "dish";
  if (action.startsWith("visitor_")) return "visitor";
  if (action.startsWith("employee_import_")) return "import";
  if (action === "user_role_changed") return "role";
  if (action === "user_disabled") return "disabled";
  if (action === "user_reactivated") return "enabled";
  if (action.includes("password")) return "password";
  if (action.startsWith("super_admin_") || action === "first_admin_provisioned") return "admin";
  if (action === "user_created" || action === "user_updated") return "user";
  if (action.startsWith("auth_")) return "auth";
  return "neutral";
}

function EventIcon({ action }: { action: string }) {
  const kind = iconKind(action);
  return <span className={`activity-icon activity-icon--${kind}`} data-icon={kind} aria-hidden="true">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {iconPaths[kind]}
    </svg>
  </span>;
}

function fieldLabel(key: string) {
  const labelsByField: Record<string, string> = {
    is_received: "Order status",
    is_enabled: "Account status",
    is_active: "Dish status",
    password_change_required: "Password change",
    role: "Role",
    menu_id: "Menu",
    status: "Import status",
    total_rows: "Total rows",
    inserted_rows: "Inserted rows",
    updated_rows: "Updated rows",
    unchanged_rows: "Unchanged rows",
    rejected_rows: "Rejected rows",
  };
  return labelsByField[key] ?? key.replaceAll("_", " ");
}

function fieldValue(key: string, value: SafeValue) {
  if (value === null) return "None";
  if (key === "is_received") return value ? "Received" : "Pending";
  if (key === "is_enabled") return value ? "Enabled" : "Disabled";
  if (key === "is_active") return value ? "Active" : "Inactive";
  if (key === "password_change_required") return value ? "Required" : "Not required";
  if (key === "role" && typeof value === "string") {
    return ({ assistant_admin: "Assistant Admin", super_admin: "Super Admin", admin: "Admin" } as Record<string, string>)[value] ?? value;
  }
  if (key === "status" && typeof value === "string") return value.replaceAll("_", " ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function targetLabel(entry: Entry) {
  if (!entry.entity_type) return "Restricted reference";
  const entities: Record<string, string> = {
    employee_imports: "Employee import",
    menu_dates: "Menu date",
    orders: "Order",
    menus: "Menu",
    dishes: "Dish",
    visitors: "Visitor",
    users: "User",
  };
  return `${entities[entry.entity_type] ?? entry.entity_type.replaceAll("_", " ")}${entry.reference ? ` #${entry.reference}` : ""}`;
}

function safeChanges(before: Entry["before"], after: Entry["after"]) {
  const keys = Object.keys(before);
  for (const key of Object.keys(after)) {
    if (!keys.includes(key)) keys.push(key);
  }
  if (!keys.length) return <p className="activity-no-changes">No additional safe fields are available.</p>;
  return <dl className="activity-changes">{keys.map(key => (
    <div className="activity-change" key={key}>
      <dt>{fieldLabel(key)}</dt>
      <dd>{key in before ? fieldValue(key, before[key]) : "—"}</dd>
      <span className="activity-change-arrow" aria-hidden="true">→</span>
      <dd>{key in after ? fieldValue(key, after[key]) : "—"}</dd>
    </div>
  ))}</dl>;
}

function EventDetails({ entry }: { entry: Entry }) {
  return <details className="activity-details">
    <summary><span>View safe details</span><span className="activity-details-mark" aria-hidden="true">+</span></summary>
    <div className="activity-detail-content">
      {entry.local_operator && <p><strong>Local operator (self-attested)</strong><span>{entry.local_operator}</span></p>}
      {entry.reason && <p><strong>Correction reason</strong><span>{entry.reason}</span></p>}
      {safeChanges(entry.before, entry.after)}
    </div>
  </details>;
}

export default function ActivityWorkspace({ request }: { request: RequestApi }) {
  const [filters, setFilters] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams(filters);
    if (cursor) query.set("cursor", cursor);
    request<Page>(`/api/activity?${query}`, { signal: controller.signal })
      .then(value => {
        if (!controller.signal.aborted) {
          setPage(value);
          setError("");
          setLoading(false);
        }
      })
      .catch(err => {
        if (!controller.signal.aborted) {
          setPage(null);
          setError(err instanceof Error ? err.message : "Unable to load activity.");
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [request, filters, cursor]);

  function search(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const params = new URLSearchParams();
    for (const name of ["start", "end", "actor_id", "action", "entity", "reference"]) {
      const value = String(data.get(name) ?? "").trim();
      if (value) params.set(name, value);
    }
    if (params.get("start") && params.get("end") && params.get("start")! > params.get("end")!) {
      setError("End date must be on or after start date.");
      return;
    }
    if (params.get("reference") && !params.get("entity")) {
      setError("Choose an entity when filtering by reference.");
      return;
    }
    setLoading(true);
    setError("");
    setHistory([]);
    setCursor(null);
    const next = params.toString();
    if (next === filters && cursor === null) {
      setLoading(false);
      return;
    }
    setFilters(next);
  }

  return <section className="activity-workspace" aria-labelledby="activity-heading">
    <header className="activity-page-header">
      <div className="activity-page-heading">
        <span className="activity-eyebrow"><span aria-hidden="true" /> AUDIT &amp; GOVERNANCE</span>
        <h2 id="activity-heading">Activity Logs</h2>
        <p>Review recorded system changes and account activity.</p>
      </div>
      <p className="activity-context">Recorded events only <span aria-hidden="true">·</span> Times shown in Philippine time <span aria-hidden="true">·</span> Some historical actions were not logged</p>
    </header>

    <form className="activity-toolbar" onSubmit={search} aria-label="Filter activity logs">
      <div className="activity-toolbar-heading">
        <div><span className="activity-toolbar-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5h16l-6.5 7.5V19l-3 1v-7.5z" /></svg></span>
          <div><h3>Filter activity</h3><p>Refine the recorded event list</p></div></div>
        <span className="activity-toolbar-hint">All filters are optional</span>
      </div>
      <div className="activity-filter-grid">
        <label>From<input type="date" name="start" /></label>
        <label>To<input type="date" name="end" /></label>
        <label>Actor user ID<input type="number" name="actor_id" min="1" placeholder="Any actor" /></label>
        <label>Action<select name="action"><option value="">All actions</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>Entity<select name="entity"><option value="">All entities</option>{["orders", "menus", "menu_dates", "dishes", "visitors", "employee_imports", "users"].map(entity => <option key={entity} value={entity}>{entity.replaceAll("_", " ")}</option>)}</select></label>
        <label>Reference<input name="reference" inputMode="numeric" maxLength={40} placeholder="Entity reference" /></label>
        <button type="submit">Apply filters</button>
      </div>
    </form>

    <div className="activity-results-heading">
      <div><span className="activity-results-kicker">EVENT HISTORY</span><h3>Recent activity</h3></div>
      <span className="activity-sort-label"><span aria-hidden="true">↓</span> Newest first</span>
    </div>

    {loading && <div className="activity-state activity-state--loading" role="status"><span className="activity-state-mark" aria-hidden="true" />Loading activity…</div>}
    {error && <p className="activity-error" role="alert"><span aria-hidden="true">!</span>{error}</p>}
    {!loading && !error && !page?.items.length && <div className="activity-state activity-state--empty" role="status">
      <span className="activity-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4h14v16H5zM8 8h8M8 12h5" /></svg></span>
      <strong>No activity matches these filters</strong><span>Try a wider date range or remove one or more filters.</span>
    </div>}

    {!loading && !error && !!page?.items.length && <ol className="activity-ledger" aria-label="Activity event ledger">
      {page.items.map(entry => <li className="activity-ledger-row" key={entry.id}>
        <article className="activity-event" aria-label={`${labels[entry.action] ?? "Unknown event"}, event ${entry.id}`}>
          <EventIcon action={entry.action} />
          <div className="activity-event-body">
            <div className="activity-event-title-line">
              <h4>{labels[entry.action] ?? "Unknown event"}</h4>
              <span className="activity-event-id">#{entry.id}</span>
            </div>
            <div className="activity-event-meta">
              <span className="activity-event-actor"><strong>{entry.actor_display_name}</strong><span>Current name · user #{entry.actor_id}</span></span>
              <span className="activity-event-target">{targetLabel(entry)}</span>
              <time dateTime={entry.occurred_at}>{new Intl.DateTimeFormat("en-PH", {
                dateStyle: "medium", timeStyle: "medium", timeZone: "Asia/Manila",
              }).format(new Date(entry.occurred_at))} <span>PHT</span></time>
            </div>
            <EventDetails entry={entry} />
          </div>
        </article>
      </li>)}
    </ol>}

    {!loading && !error && page && <nav className="activity-pagination" aria-label="Activity log pages">
      <button type="button" className="secondary" disabled={!history.length} onClick={() => {
        setLoading(true);
        setCursor(history[history.length - 1]);
        setHistory(history.slice(0, -1));
      }}><span aria-hidden="true">←</span> Previous</button>
      <span aria-current="page">Page {history.length + 1}</span>
      <button type="button" className="secondary" disabled={!page.next_cursor} onClick={() => {
        setLoading(true);
        setHistory([...history, cursor]);
        setCursor(page.next_cursor);
      }}>Next <span aria-hidden="true">→</span></button>
    </nav>}
  </section>;
}
