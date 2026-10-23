import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

function render(open, disabled = false) {
  const updates = [], downloads = [], refs = [{ current: { contains: () => false } }, { current: { focus() {} } }, { current: { focus() {} } }, { current: { focus() {} } }];
  const listeners = {};
  const react = { useState: () => [open, value => updates.push(value)], useRef: () => refs.shift(), useEffect: fn => fn() };
  const jsx = (type, props) => ({ type, props });
  const source = readFileSync(new URL("../src/components/report-download-menu.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } }).outputText;
  const previous = globalThis.document;
  const previousFrame = globalThis.requestAnimationFrame;
  globalThis.document = { addEventListener: (name, fn) => { listeners[name] = fn; }, removeEventListener() {}, activeElement: null };
  globalThis.requestAnimationFrame = fn => { fn(); };
  const exports = {}; new Function("require", "exports", code)(name => name === "react" ? react : { jsx, jsxs: jsx }, exports);
  const tree = exports.default({ disabled, onDownload: value => downloads.push(value) }); const nodes = [];
  function visit(node) { if (!node || typeof node !== "object") return; if (Array.isArray(node)) return node.forEach(visit); nodes.push(node); visit(node.props.children); }
  visit(tree);
  return { tree, nodes, updates, downloads, listeners, restore: () => { globalThis.document = previous; globalThis.requestAnimationFrame = previousFrame; } };
}

test("download trigger opens menu without downloading and is disabled when unavailable", () => {
  const ui = render(false); try {
    const button = ui.nodes.find(node => node.type === "button");
    assert.equal(button.props["aria-haspopup"], "menu"); assert.equal(button.props["aria-expanded"], false);
    button.props.onClick(); assert.deepEqual(ui.updates, [true]); assert.deepEqual(ui.downloads, []);
  } finally { ui.restore(); }
  const disabled = render(false, true); try { assert.equal(disabled.nodes.find(n => n.type === "button").props.disabled, true); } finally { disabled.restore(); }
});

test("download menu selects formats and closes on Escape and outside click", () => {
  const ui = render(true); try {
    const options = ui.nodes.filter(node => node.props.role === "menuitem");
    assert.equal(options.length, 2); options[0].props.onClick(); options[1].props.onClick();
    assert.deepEqual(ui.downloads, ["excel", "pdf"]);
    let prevented = false; ui.tree.props.onKeyDown({ key: "Escape", preventDefault() { prevented = true; } });
    assert.ok(prevented);
    prevented = false; ui.tree.props.onKeyDown({ key: "ArrowDown", preventDefault() { prevented = true; } }); assert.ok(prevented);
    ui.listeners.pointerdown({ target: {} });
    assert.ok(ui.updates.every(value => value === false));
  } finally { ui.restore(); }
});
