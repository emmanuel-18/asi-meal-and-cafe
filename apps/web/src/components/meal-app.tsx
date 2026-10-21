"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest, type ApiOptions, type RequestApi, type Session } from "@/lib/api";
import OrderEntry from "./order-entry";
import OrderRegister from "./order-register";
import MenuWorkspace from "./menu-workspace";
import EmployeeDirectory from "./employee-directory";
import ReportsWorkspace from "./reports-workspace";

const sections = ["Orders", "Menu", "Employees", "Visitors", "Reports"] as const;
type Section = typeof sections[number];
const deferred: Record<Exclude<Section, "Orders" | "Menu" | "Employees" | "Reports">, string> = {
  Visitors: "A dedicated visitor directory screen is planned for a later stage. Search, select, or create a visitor during order entry.",
};

export default function MealApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [notice, setNotice] = useState("");
  const [section, setSection] = useState<Section>("Orders");
  const [entry, setEntry] = useState(false);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const authEpoch = useRef(0);
  const authenticated = useRef(false);
  const csrf = session?.csrf_token;

  const check = useCallback((signal?: AbortSignal) => {
    const epoch = authEpoch.current;
    return apiRequest<Session>("/auth/me", { signal }).then(verified => {
      if (epoch !== authEpoch.current) return;
      authenticated.current = true; setSession(verified); setNotice("");
    }).catch(error => {
      if (epoch !== authEpoch.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      if (error instanceof ApiError && error.status === 401) {
        if (authenticated.current) setNotice("Your session has expired. Please sign in again.");
        authenticated.current = false; setSession(null); setSavedId(null); setEntry(false);
      }
      else setNotice("Unable to check your session. Check that the API is available, then retry.");
    }).finally(() => { if (!signal?.aborted) setChecking(false); });
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void check(controller.signal);
    const focus = () => { void check(); };
    window.addEventListener("focus", focus);
    return () => { controller.abort(); window.removeEventListener("focus", focus); };
  }, [check]);

  const request: RequestApi = useCallback(async <T,>(path: string, options?: ApiOptions): Promise<T> => {
    try { return await apiRequest<T>(path, options, csrf); }
    catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        authEpoch.current++; authenticated.current = false;
        setSession(null); setSavedId(null); setEntry(false);
        setNotice("Your session has expired. Please sign in again.");
      }
      throw error;
    }
  }, [csrf]);

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = form.elements.namedItem("password") as HTMLInputElement;
    authEpoch.current++; setBusy(true); setNotice("");
    try {
      const verified = await apiRequest<Session>("/auth/login", { method: "POST", body: {
        login_name: String(data.get("login_name")), password: String(data.get("password")),
      } });
      authEpoch.current++; authenticated.current = true;
      setSession(verified); setSection("Orders"); setEntry(false); setSavedId(null);
    } catch (error) {
      setNotice(error instanceof ApiError && error.status === 401 ? "Sign-in failed. Check your login name and password." :
        error instanceof Error ? error.message : "Sign-in failed.");
    } finally { password.value = ""; setBusy(false); }
  }

  async function logout() {
    authEpoch.current++; setBusy(true); setNotice("");
    try {
      await request<void>("/auth/logout", { method: "POST" });
      authEpoch.current++; authenticated.current = false;
      setSession(null); setSavedId(null); setEntry(false); setNotice("Signed out.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Unable to sign out. Please retry."); }
    finally { setBusy(false); }
  }

  return <>
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="app-header"><div className="brand"><h1>ASI Meal Management</h1><p>Meal Sales &amp; Payment Tracking</p></div>
      {session && <div className="account"><span>{session.user.display_name}<small>{session.user.role === "admin" ? "Admin" : "Assistant Admin"}</small></span>
        <button type="button" className="secondary" onClick={() => void logout()} disabled={busy}>Sign out</button></div>}
    </header>
    {session && <nav className="app-nav" aria-label="Application">{sections.map(name => <button key={name} type="button"
      aria-current={section === name ? "page" : undefined} onClick={() => setSection(name)}>{name}</button>)}</nav>}
    <main id="main" tabIndex={-1} className={session ? "workspace" : "login-space"}>
      {notice && <div className="notice" role="status">{notice}<button type="button" className="text-button" onClick={() => void check()}>Check session</button></div>}
      {checking ? <p role="status">Checking session…</p> : !session ? <section className="panel login-panel">
        <h2>Sign in</h2><p className="muted">Use your individual ASI Meal account.</p>
        <form onSubmit={login}><label>Login name<input name="login_name" required maxLength={255} autoComplete="username" autoCapitalize="none" spellCheck={false} /></label>
          <label>Password<input name="password" type="password" required maxLength={1024} autoComplete="current-password" /></label>
          <button disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}</button></form>
      </section> : section === "Menu" ? <MenuWorkspace request={request} /> : section === "Employees" ? <EmployeeDirectory request={request} role={session.user.role} /> : section === "Reports" ? <ReportsWorkspace request={request} /> : section !== "Orders" ? <section className="panel"><h2>{section}</h2><p>{deferred[section]}</p><p className="muted">Not implemented in this stage.</p></section> : <>
        <div className="section-heading"><h2>{entry ? "New meal order" : "Orders"}</h2>
          <button type="button" className={entry ? "secondary" : ""} onClick={() => { setEntry(!entry); setSavedId(null); }}>
            {entry ? "Back to orders" : "New order"}</button></div>
        {entry ? <OrderEntry request={request} onSaved={id => { setSavedId(id); setEntry(false); }} /> :
          <OrderRegister request={request} session={session} savedId={savedId} />}
      </>}
    </main>
  </>;
}
