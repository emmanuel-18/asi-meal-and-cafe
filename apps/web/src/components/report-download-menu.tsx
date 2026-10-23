"use client";

import { useEffect, useRef, useState } from "react";

export default function ReportDownloadMenu({ disabled, onDownload }: { disabled: boolean; onDownload: (format: "excel" | "pdf") => void }) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLButtonElement>(null);
  const second = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) { if (!container.current?.contains(event.target as Node)) setOpen(false); }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  function keydown(event: React.KeyboardEvent) {
    if (event.key === "Escape") { event.preventDefault(); setOpen(false); trigger.current?.focus(); }
    else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) { const target = event.key === "ArrowDown" ? first : second; setOpen(true); requestAnimationFrame(() => target.current?.focus()); }
      else if (document.activeElement === first.current) second.current?.focus();
      else first.current?.focus();
    } else if (event.key === "Tab") setOpen(false);
  }

  return <div className="report-download" ref={container} onKeyDown={keydown}>
    <button ref={trigger} type="button" disabled={disabled} aria-haspopup="menu" aria-expanded={open && !disabled}
      onClick={() => { if (!open) { setOpen(true); requestAnimationFrame(() => first.current?.focus()); } else setOpen(false); }}>
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3v12m-4-4 4 4 4-4M4 17v3h16v-3" /></svg>
      Download Report <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 9 6 6 6-6" /></svg>
    </button>
    {open && !disabled && <div className="report-download-options" role="menu" aria-label="Download report format">
      <button ref={first} role="menuitem" type="button" onClick={() => { setOpen(false); onDownload("excel"); }}><svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16v16H4zM4 10h16M10 4v16" /></svg><span>Excel (.xlsx)</span></button>
      <button ref={second} role="menuitem" type="button" onClick={() => { setOpen(false); onDownload("pdf"); }}><svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6" /></svg><span>PDF (.pdf)</span></button>
    </div>}
  </div>;
}
