import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const entry = readFileSync(new URL("../src/components/order-entry.tsx", import.meta.url), "utf8");
const register = readFileSync(new URL("../src/components/order-register.tsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/components/meal-app.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");

test("Orders workspace exposes the compact header and sequenced order entry", () => {
  assert.match(app, /className="orders-page-header"/);
  assert.match(app, /ORDER OPERATIONS/);
  for (const section of ["Service date", "Customer", "Menu items", "Payment allocation"]) {
    assert.match(entry, new RegExp(`>${section}<|${section}`));
  }
  assert.match(entry, /className="order-workspace order-entry-workspace"/);
  assert.match(entry, /className="panel customer-panel order-entry-section"/);
  assert.match(entry, /className="panel items-panel order-entry-section"/);
  assert.match(entry, /className="panel payment-panel order-entry-section"/);
  assert.match(entry, /Save Pending order/);
  assert.match(entry, /Allocations must balance before Received/);
});

test("Order register preserves server totals and separates mobile selection from receipt action", () => {
  for (const field of ["pending", "received", "total", "recognized_sales"]) {
    assert.match(register, new RegExp(`overview\\.${field}`));
  }
  assert.match(register, /className="orders-mobile-list"/);
  assert.match(register, /className="order-mobile-open"/);
  assert.match(register, /\? "Close" : "Open"/);
  assert.match(register, /aria-label=\{`Mark order \$\{order\.order_id\} Received`\}/);
  assert.match(register, /onClick=\{\(\) => toggleDetail\(order\.order_id\)\}/);
  assert.match(register, /detail\?\.order_id === id[\s\S]*?setDetail\(null\)/);
  assert.match(register, /Close details/);
  assert.match(register, /void quickReceive\(order\)/);
  assert.match(register, /className={`order-row\$\{detail\?\.order_id === order\.order_id/);
});

test("Orders touch controls have 44px targets in the compact register layout", () => {
  const compactLayout = styles.match(/@container \(max-width: 820px\) \{([\s\S]*?)\n\}/)?.[1] ?? "";
  assert.match(compactLayout, /\.pagination button, \.order-detail-panel \.section-heading > button \{ min-width: 44px; min-height: 44px; \}/);
  assert.doesNotMatch(styles, /\.pagination button \{ min-width: 44px; min-height: 44px; \}/);
});

test("Order detail uses a modal and guards closure during edits and corrections", () => {
  assert.match(register, /element\.showModal\(\)/);
  assert.match(register, /if \(busy \|\| editing \|\| reversing\) return/);
  assert.match(register, /onCancel=\{event => \{ event\.preventDefault\(\); closeDetail\(\); \}\}/);
  assert.match(register, /detailTrigger\.current\?\.isConnected/);
  assert.match(styles, /\.order-detail-drawer::backdrop/);
  assert.match(styles, /width: 100vw; padding-bottom: env\(safe-area-inset-bottom\)/);
});
