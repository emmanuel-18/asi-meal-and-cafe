"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest, type ApiOptions, type RequestApi, type Session } from "@/lib/api";
import OrderEntry from "./order-entry";
import OrderRegister from "./order-register";
import MenuWorkspace from "./menu-workspace";
import CustomersWorkspace from "./customers-workspace";
import ReportsWorkspace from "./reports-workspace";
import AppNavigation, { type Section } from "./app-navigation";
import UsersWorkspace from "./users-workspace";
import ActivityWorkspace from "./activity-workspace";

export default function MealApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [notice, setNotice] = useState("");
  const [section, setSection] = useState<Section>("Orders");
  const [entry, setEntry] = useState(false);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [menuDate, setMenuDate] = useState<string | undefined>();
  const [menuRevision, setMenuRevision] = useState(0);
  const menuSaved = useCallback(() => setMenuRevision(value => value + 1), []);
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

  async function changePassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    setBusy(true); setNotice("");
    try {
      const verified = await request<Session>("/auth/change-password", { method: "POST", body: {
        current_password: data.get("current_password"), new_password: data.get("new_password"),
      } });
      setSession(verified); setNotice("Password changed."); form.reset();
    } catch (error) { setNotice(error instanceof Error ? error.message : "Unable to change password."); }
    finally { form.reset(); setBusy(false); }
  }

  return <div className={`app-shell${session ? "" : " is-signed-out"}`}>
    <a className="skip-link" href="#main">Skip to content</a>
    {!session && <header className="app-header login-header"><div className="brand"><h1>ASI Meal Management</h1><p>Meal Sales &amp; Payment Tracking</p></div></header>}
    {session && !session.user.password_change_required && <AppNavigation session={session} section={section} onSelect={setSection} onLogout={() => void logout()} busy={busy} />}
    <main id="main" tabIndex={-1} className={session ? "workspace" : "login-space"}>
      {notice && <div className={`notice${notice === "Signed out." ? " signed-out-notice" : ""}`} role="status">{notice}{notice !== "Signed out." && <button type="button" className="text-button" onClick={() => void check()}>Try again</button>}</div>}
      {checking ? <p role="status">Checking session…</p> : !session ? <section className="panel login-panel">
        <h2>Sign in</h2><p className="muted">Enter your individual ASI Meal account details.</p>
        <form onSubmit={login}><label>Login name<input name="login_name" required maxLength={255} autoComplete="username" autoCapitalize="none" spellCheck={false} /></label>
          <label>Password<input name="password" type="password" required maxLength={1024} autoComplete="current-password" /></label>
          <button disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}</button></form>
      </section> : session.user.password_change_required ? <section className="panel login-panel"><h2>Change your password</h2><p>Change your temporary password before continuing.</p><form onSubmit={changePassword}><label>Current password<input name="current_password" type="password" autoComplete="current-password" required /></label><label>New password<input name="new_password" type="password" autoComplete="new-password" minLength={8} required /></label><button disabled={busy}>Change password</button><button type="button" className="secondary" onClick={() => void logout()} disabled={busy}>Sign out</button></form></section> : section === "Activity Logs" && session.user.role === "super_admin" ? <ActivityWorkspace request={request} /> : section === "Users" && session.user.role === "super_admin" ? <UsersWorkspace request={request} /> : section === "Menu" ? <MenuWorkspace request={request} initialDate={menuDate} onSaved={menuSaved} /> : section === "Customers" ? <CustomersWorkspace request={request} role={session.user.role} /> : section === "Reports" ? <ReportsWorkspace request={request} /> : <>
        <header className="orders-page-header">
          <div className="orders-page-heading">
            <span className="orders-eyebrow"><span aria-hidden="true" /> ORDER OPERATIONS</span>
            <h2>{entry ? "New meal order" : "Orders"}</h2>
            <p>{entry ? "Choose a customer, add menu items, then review payment allocations." : "Review orders and record meal handover."}</p>
          </div>
          <button type="button" className={entry ? "secondary orders-page-action" : "brand-accent orders-page-action"} onClick={() => { setEntry(!entry); setSavedId(null); }}>
            {entry ? "Back to orders" : "New order"}
          </button>
        </header>
        {!entry && <OrderRegister request={request} session={session} savedId={savedId} />}
      </>}
      {session && !session.user.password_change_required && entry && <div hidden={section !== "Orders"}><OrderEntry request={request} menuRevision={menuRevision}
        onConfigureMenu={day => { setMenuDate(day); setSection("Menu"); }} onSaved={id => { setSavedId(id); setEntry(false); }} /></div>}
    </main>
  </div>;
}
