"use client";

import { useRef, useState } from "react";
import type { RequestApi, Role } from "@/lib/api";
import EmployeeDirectory from "./employee-directory";
import VisitorDirectory from "./visitor-directory";

export default function CustomersWorkspace({ request, role }: { request: RequestApi; role: Role }) {
  const [tab, setTab] = useState<"employees" | "visitors">("employees");
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const names = ["employees", "visitors"] as const;
  return <div><div role="tablist" aria-label="Customer directories" className="customer-tabs">{names.map((name, index) =>
    <button key={name} ref={el => { tabs.current[index] = el; }} role="tab" id={`customer-tab-${name}`} aria-controls={`customer-panel-${name}`}
      aria-selected={tab === name} tabIndex={tab === name ? 0 : -1} onClick={() => setTab(name)} onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - index;
        setTab(names[next]); tabs.current[next]?.focus();
      }}>{name === "employees" ? "Employees" : "Visitors"}</button>)}</div>
    <div role="tabpanel" id="customer-panel-employees" aria-labelledby="customer-tab-employees" hidden={tab !== "employees"}><EmployeeDirectory request={request} role={role} /></div>
    <div role="tabpanel" id="customer-panel-visitors" aria-labelledby="customer-tab-visitors" hidden={tab !== "visitors"}><VisitorDirectory request={request} /></div>
  </div>;
}
