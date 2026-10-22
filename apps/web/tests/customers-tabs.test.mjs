import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

test("customer tabs expose selected state and keyboard navigation", () => {
  let selected = "employees", focused = 0;
  const refs = { current: [{ focus() {} }, { focus() { focused++; } }] };
  const react = { useState: initial => [initial, value => { selected = value; }], useRef: () => refs };
  const jsx = (type, props) => ({ type, props: props ?? {} });
  const source = readFileSync(new URL("../src/components/customers-workspace.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  new Function("require", "exports", code)(name => name === "react" ? react : name === "react/jsx-runtime" ? { jsx, jsxs: jsx } : { default: () => null }, exports);
  const tree = exports.default({ request: () => {}, role: "admin" });
  const tablist = tree.props.children[0];
  assert.equal(tablist.props.role, "tablist");
  const tabs = tablist.props.children;
  assert.equal(tabs[0].props["aria-selected"], true);
  assert.equal(tabs[1].props.tabIndex, -1);
  let prevented = false;
  tabs[0].props.onKeyDown({ key: "ArrowRight", preventDefault() { prevented = true; } });
  assert.equal(prevented, true); assert.equal(selected, "visitors"); assert.equal(focused, 1);
  assert.equal(tree.props.children[1].props.role, "tabpanel");
  assert.equal(tree.props.children[2].props.hidden, true);
});
