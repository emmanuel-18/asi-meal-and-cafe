import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

test("temporary-password sessions show the password-change form and no operational navigation", () => {
  let stateIndex = 0;
  const session = {user: {id: 42, display_name: "Synthetic User", role: "admin", password_change_required: true}, csrf_token: "synthetic"};
  const react = {useState: initial => [stateIndex++ === 0 ? session : stateIndex === 2 ? false : initial, () => {}], useRef: initial => ({current: initial}), useEffect: () => {}, useCallback: fn => fn};
  const jsx = (type, props) => ({type, props: props ?? {}});
  const code = ts.transpileModule(readFileSync(new URL("../src/components/meal-app.tsx", import.meta.url), "utf8"), {compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS}}).outputText;
  const exports = {};
  new Function("require", "exports", code)(name => name === "react" ? react : name === "react/jsx-runtime" ? {jsx, jsxs: jsx} : name === "@/lib/api" ? {apiRequest: () => {}} : {default: () => null}, exports);
  const tree = exports.default(); const nodes = [];
  function visit(node) { if (!node || typeof node !== "object") return; if (Array.isArray(node)) return node.forEach(visit); nodes.push(node); visit(node.props.children); }
  visit(tree);
  assert.ok(nodes.some(node => node.type === "h2" && node.props.children === "Change your password"));
  assert.ok(nodes.some(node => node.type === "input" && node.props.name === "current_password"));
  assert.ok(nodes.some(node => node.type === "input" && node.props.name === "new_password"));
  assert.ok(!nodes.some(node => typeof node.type === "function"));
});
