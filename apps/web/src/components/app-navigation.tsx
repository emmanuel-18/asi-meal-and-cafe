"use client";

import { useEffect, useRef } from "react";
import type { Session } from "@/lib/api";

export const sections = ["Orders", "Menu", "Customers", "Reports", "Users"] as const;
export type Section = typeof sections[number];

function Icon({ name }: { name: Section | "Navigation" | "Close" | "Sign out" }) {
  const paths: Record<typeof name, React.ReactNode> = {
    Orders: <><path d="M5 3h14v18l-3-2-4 2-4-2-3 2z"/><path d="M8 8h8M8 12h8"/></>,
    Menu: <><path d="M4 3v7a3 3 0 0 0 6 0V3M7 3v18M17 3c-2 2-3 5-3 8h4V3zM18 11v10"/></>,
    Customers: <><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M17 14a5 5 0 0 1 4 5v1"/></>,
    Reports: <><path d="M4 20h16M6 17v-5h3v5M11 17V7h3v10M16 17V4h3v13"/></>,
    Users: <><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 10h5M18.5 7.5v5"/></>,
    Navigation: <path d="M4 6h16M4 12h16M4 18h16"/>,
    Close: <path d="M5 5l14 14M19 5 5 19"/>,
    "Sign out": <><path d="M10 4H5v16h5M14 8l4 4-4 4M8 12h10"/></>,
  };
  return <svg aria-hidden="true" className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

export default function AppNavigation({ session, section, onSelect, onLogout, busy }: {
  session: Session; section: Section; onSelect: (section: Section) => void; onLogout: () => void; busy: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const navigating = useRef(false);
  const oldOverflow = useRef("");
  const locked = useRef(false);

  function open() {
    if (!dialog.current || dialog.current.open) return;
    oldOverflow.current = document.body.style.overflow;
    dialog.current.showModal();
    document.body.style.overflow = "hidden";
    locked.current = true;
  }
  function closed() {
    document.body.style.overflow = oldOverflow.current;
    locked.current = false;
    if (navigating.current) {
      navigating.current = false;
      requestAnimationFrame(() => { const heading = document.querySelector<HTMLElement>("#main h2"); heading?.setAttribute("tabindex", "-1"); heading?.focus(); });
    } else trigger.current?.focus();
  }
  function select(name: Section, fromDrawer: boolean) {
    onSelect(name);
    if (fromDrawer && dialog.current?.open) { navigating.current = true; dialog.current.close(); }
  }
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1024px)");
    const resize = () => { if (media.matches && dialog.current?.open) { navigating.current = true; dialog.current.close(); } };
    media.addEventListener("change", resize);
    return () => { media.removeEventListener("change", resize); if (locked.current) document.body.style.overflow = oldOverflow.current; };
  }, []);

  function content(fromDrawer: boolean) {
    return <><div className="sidebar-brand">ASI Meal Management</div>
      <nav className="sidebar-nav" aria-label="Application">{sections.filter(name => name !== "Users" || session.user.role === "super_admin").map(name => <button type="button" key={name}
        aria-current={section === name ? "page" : undefined} onClick={() => select(name, fromDrawer)}><Icon name={name}/><span>{name}</span></button>)}</nav>
      <div className="sidebar-account"><span>{session.user.display_name}<small>{session.user.role === "super_admin" ? "Super Admin" : session.user.role === "admin" ? "Admin" : "Assistant Admin"}</small></span>
        <button type="button" onClick={onLogout} disabled={busy}><Icon name="Sign out"/>Sign out</button></div></>;
  }

  return <><aside className="desktop-sidebar">{content(false)}</aside>
    <header className="mobile-header"><strong>ASI Meal Management</strong><button type="button" ref={trigger} onClick={open} aria-haspopup="dialog" aria-controls="navigation-drawer"><Icon name="Navigation"/>Menu</button></header>
    <dialog id="navigation-drawer" ref={dialog} className="navigation-drawer" aria-label="Application navigation" onClose={closed}>
      <button type="button" className="drawer-close" onClick={() => dialog.current?.close()} autoFocus><Icon name="Close"/>Close</button>
      {content(true)}
    </dialog></>;
}
