import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Exercise the component's handlers with a small dialog double. Native dialog
// focus containment and rendering still require real-browser verification.
function render(role = "admin", section = "Orders") {
  const effects = [];
  const jsx = (type, props) => ({ type, props: props ?? {} });
  const react = { useRef: initial => ({ current: initial }), useEffect: callback => effects.push(callback) };
  const source = readFileSync(new URL("../src/components/app-navigation.tsx", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  new Function("require", "exports", compiled)(name => name === "react" ? react : { jsx, jsxs: jsx, Fragment: "fragment" }, exports);
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
  return { nodes, trigger, drawer, fakeDialog, media, get selection() { return selection; }, get signouts() { return signouts; },
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
      assert.equal(ui.nodes.filter(n => n.type === "button" && n.props.children?.[1] === "Sign out").length, 2);
      assert.equal(ui.nodes.some(n => n.type === "small" && n.props.children === (role === "admin" ? "Admin" : "Assistant Admin")), true);
      ui.nodes.find(n => n.type === "button" && n.props.children?.[1] === "Sign out").props.onClick();
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
