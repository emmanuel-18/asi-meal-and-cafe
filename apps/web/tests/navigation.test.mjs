import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Exercise the component's handlers with a small dialog double. Native dialog
// focus containment and rendering still require real-browser verification.
function render(role = "admin", section = "Orders", collapsed = false) {
  const effects = [];
  const jsx = (type, props) => ({ type, props: props ?? {} });
  let nextCollapsed = collapsed;
  const react = { useState: () => [collapsed, value => { nextCollapsed = typeof value === "function" ? value(nextCollapsed) : value; }], useRef: initial => ({ current: initial }), useEffect: callback => effects.push(callback) };
  const source = readFileSync(new URL("../src/components/app-navigation.tsx", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  const Image = props => jsx("img", props);
  new Function("require", "exports", compiled)(name => name === "react" ? react : name === "next/image" ? { default: Image } : { jsx, jsxs: jsx, Fragment: "fragment" }, exports);
  let selection, signouts = 0, triggerFocused = 0, headingFocused = 0;
  const heading = { setAttribute: (name, value) => assert.deepEqual([name, value], ["tabindex", "-1"]), focus: () => headingFocused++ };
  const oldDocument = globalThis.document, oldWindow = globalThis.window, oldRaf = globalThis.requestAnimationFrame;
  globalThis.document = { body: { style: { overflow: "scroll" } }, querySelector: () => heading };
  const media = { matches: false, addEventListener() {}, removeEventListener() {} };
  globalThis.window = { matchMedia: () => media };
  globalThis.requestAnimationFrame = callback => callback();
  const tree = exports.default({ session: { user: { display_name: "Synthetic User", role } }, section,
    onSelect: value => { selection = value; }, onLogout: () => { signouts++; }, busy: false });
  const nodes = [];
  function visit(node) { if (!node || typeof node !== "object") return; if (Array.isArray(node)) { node.forEach(visit); return; } nodes.push(node); visit(node.props.children); }
  visit(tree);
  const drawer = nodes.find(n => n.type === "dialog");
  const trigger = nodes.find(n => n.type === "button" && n.props["aria-controls"] === "navigation-drawer");
  const fakeDialog = { open: false, showModal() { this.open = true; }, close() { this.open = false; drawer.props.onClose(); } };
  drawer.props.ref.current = fakeDialog;
  trigger.props.ref.current = { focus: () => triggerFocused++ };
  const cleanup = effects.map(fn => fn());
  return { nodes, trigger, drawer, fakeDialog, media, get collapsed() { return nextCollapsed; }, get selection() { return selection; }, get signouts() { return signouts; },
    get triggerFocused() { return triggerFocused; }, get headingFocused() { return headingFocused; },
    restore() { cleanup.forEach(fn => fn?.()); globalThis.document = oldDocument; globalThis.window = oldWindow; globalThis.requestAnimationFrame = oldRaf; } };
}

test("navigation exposes four labeled destinations, active page and both account roles", () => {
  for (const role of ["admin", "assistant_admin"]) {
    const ui = render(role, "Reports");
    try {
      const buttons = ui.nodes.filter(n => n.type === "button" && n.props["aria-current"] === "page");
      assert.equal(buttons.length, 2); // desktop and drawer
      assert.ok(buttons.every(n => n.props.children[1].props.children === "Reports"));
      for (const label of ["Orders", "Menu", "Customers", "Reports"]) assert.equal(ui.nodes.filter(n => n.type === "button" && n.props.children?.[1]?.props?.children === label).length, 2);
      assert.equal(ui.nodes.filter(n => n.type === "button" && n.props.title === "Sign out").length, 2);
      assert.equal(ui.nodes.some(n => n.type === "small" && n.props.children === (role === "admin" ? "Admin" : "Assistant Admin")), true);
      ui.nodes.find(n => n.type === "button" && n.props.title === "Sign out").props.onClick();
      assert.equal(ui.signouts, 1);
    } finally { ui.restore(); }
  }
});

test("drawer opens modally, closes to its trigger, and selection focuses the destination", () => {
  const ui = render();
  try {
    ui.trigger.props.onClick();
    assert.equal(ui.fakeDialog.open, true); assert.equal(document.body.style.overflow, "hidden");
    ui.fakeDialog.close(); // The browser closes the native dialog on Escape.
    assert.equal(ui.triggerFocused, 1); assert.equal(document.body.style.overflow, "scroll");
    ui.trigger.props.onClick();
    const reports = ui.nodes.filter(n => n.type === "button" && n.props.children?.[1]?.props?.children === "Reports")[1];
    reports.props.onClick();
    assert.equal(ui.selection, "Reports"); assert.equal(ui.fakeDialog.open, false);
    assert.equal(ui.headingFocused, 1); assert.equal(document.body.style.overflow, "scroll");
  } finally { ui.restore(); }
});

test("Users is visible only to Super Admin", () => {
  for (const role of ["super_admin", "admin", "assistant_admin"]) {
    const ui = render(role);
    try {
      const users = ui.nodes.filter(n => n.type === "button" && n.props.children?.[1]?.props?.children === "Users");
      assert.equal(users.length, role === "super_admin" ? 2 : 0);
      const activity = ui.nodes.filter(n => n.type === "button" && n.props.children?.[1]?.props?.children === "Activity Logs");
      assert.equal(activity.length, role === "super_admin" ? 2 : 0);
      if (role === "super_admin") assert.ok(ui.nodes.some(n => n.type === "small" && n.props.children === "Super Admin"));
    } finally { ui.restore(); }
  }
});

test("approved branding lands on Orders and compact mode keeps accessible labels", () => {
  for (const compact of [false, true]) {
    const ui = render("super_admin", "Reports", compact);
    try {
      assert.equal(ui.nodes.find(n => n.type === "aside").props["data-collapsed"], compact);
      const toggle = ui.nodes.find(n => n.props["aria-label"] === (compact ? "Expand sidebar" : "Collapse sidebar"));
      assert.equal(toggle.props["aria-expanded"], !compact);
      toggle.props.onClick(); assert.equal(ui.collapsed, !compact);
      const brands = ui.nodes.filter(n => n.type === "button" && n.props.title === "Go to Orders");
      assert.equal(brands.length, 3);
      assert.ok(ui.nodes.some(n => n.props.src === "/brand/asi-meal-logo-reversed.svg" && n.props.alt === "ASI Meal"));
      assert.ok(ui.nodes.some(n => n.props.src === "/brand/asi-meal-symbol-reversed.svg" && n.props["aria-hidden"] === "true"));
      ui.trigger.props.onClick(); brands[2].props.onClick();
      assert.equal(ui.selection, "Orders"); assert.equal(ui.fakeDialog.open, false);
      assert.equal(ui.headingFocused, 1);
      const labels = ui.nodes.filter(n => n.type === "button" && n.props.title === "Reports");
      assert.equal(labels.length, 2); assert.ok(labels.every(n => n.props.children[1].props.children === "Reports"));
    } finally { ui.restore(); }
  }
});

test("favicon uses approved symbol artwork and framework branding is replaced", async () => {
  const { default: JSZip } = await import("jszip");
  const zip = await JSZip.loadAsync(readFileSync(new URL("../../../asi-meal-brand-svg-kit.zip", import.meta.url)));
  const expected = await zip.file("asi-meal-brand/asi-meal-symbol-reversed.svg").async("nodebuffer");
  assert.deepEqual(readFileSync(new URL("../src/app/icon.svg", import.meta.url)), expected);
  assert.deepEqual(readFileSync(new URL("../public/brand/asi-meal-symbol-reversed.svg", import.meta.url)), expected);
  const ico = readFileSync(new URL("../src/app/favicon.ico", import.meta.url));
  const { default: sharp } = await import("sharp");
  assert.equal(ico.readUInt16LE(2), 1); assert.equal(ico.readUInt16LE(4), 2);
  for (let i = 0; i < 2; i++) {
    const offset = 6 + i * 16, size = ico[offset];
    // Raster fallback uses the exact reversed SVG, including its navy tile,
    // so white/orange artwork remains visible in light and dark browser chrome.
    const png = await sharp(expected).resize(size, size).png().toBuffer();
    assert.deepEqual(ico.subarray(ico.readUInt32LE(offset + 12), ico.readUInt32LE(offset + 12) + ico.readUInt32LE(offset + 8)), png);
  }
  const layout = readFileSync(new URL("../src/app/layout.tsx", import.meta.url), "utf8");
  assert.match(layout, /applicationName: "ASI Meal Management"/);
});
