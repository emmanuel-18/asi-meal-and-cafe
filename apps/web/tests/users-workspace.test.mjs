import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/users-workspace.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
}).outputText;

const sampleAccounts = [
  { id: 2, login_name: "adminemman", display_name: "admin_emman", role: "admin", is_enabled: true, password_change_required: false, updated_at: "2026-10-23T02:00:00Z" },
  { id: 1, login_name: "superadmin", display_name: "master_emman", role: "super_admin", is_enabled: true, password_change_required: false, updated_at: "2026-10-23T01:00:00Z" },
];

function render(request) {
  const hookValues = [];
  const effects = [];
  const refs = [];
  let hookIndex = 0;
  let tree;
  let nodes = [];

  function sameDependencies(left, right) {
    return left && right && left.length === right.length && left.every((value, index) => Object.is(value, right[index]));
  }

  const react = {
    useState(initial) {
      const index = hookIndex++;
      if (!(index in hookValues)) hookValues[index] = initial;
      return [hookValues[index], value => {
        hookValues[index] = typeof value === "function" ? value(hookValues[index]) : value;
      }];
    },
    useRef(initial) {
      const index = hookIndex++;
      if (!(index in hookValues)) {
        hookValues[index] = { current: initial };
        refs.push(hookValues[index]);
      }
      return hookValues[index];
    },
    useCallback(callback, dependencies) {
      const index = hookIndex++;
      const previous = hookValues[index];
      if (previous && sameDependencies(previous.dependencies, dependencies)) return previous.callback;
      hookValues[index] = { callback, dependencies };
      return callback;
    },
    useEffect(callback, dependencies) {
      const index = hookIndex++;
      const previous = hookValues[index];
      if (!previous || !sameDependencies(previous.dependencies, dependencies)) {
        effects.push(() => {
          previous?.cleanup?.();
          const cleanup = callback();
          hookValues[index] = { dependencies, cleanup };
        });
      }
    },
  };
  const jsx = (type, props) => ({ type, props: props ?? {} });
  const exports = {};
  new Function("require", "exports", compiled)(name => name === "react" ? react : { jsx, jsxs: jsx }, exports);

  function visit(node) {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) return node.forEach(visit);
    nodes.push(node);
    visit(node.props?.children);
  }

  function refresh() {
    hookIndex = 0;
    effects.length = 0;
    tree = exports.default({ request });
    nodes = [];
    visit(tree);
    return { tree, nodes };
  }

  async function flushEffects() {
    const pending = effects.splice(0);
    pending.forEach(effect => effect());
    await new Promise(resolve => setTimeout(resolve, 0));
  }

  refresh();
  return { refresh, flushEffects, get tree() { return tree; }, get nodes() { return nodes; }, refs };
}

function nodeBy(ui, type, predicate = () => true) {
  return ui.nodes.find(node => node.type === type && predicate(node));
}

function nodeLabel(node) {
  function text(value) {
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (Array.isArray(value)) return value.map(text).join("");
    if (value && typeof value === "object") return text(value.props?.children);
    return "";
  }
  return text(node.props.children);
}

function passwordForm() {
  const input = { value: "synthetic-secret" };
  const form = {
    resetCalled: false,
    reset() { this.resetCalled = true; },
    elements: { namedItem: name => name === "password" ? input : null },
  };
  return { form, input };
}

function dialogDouble() {
  return {
    open: false,
    focusedSelector: "",
    showModal() { this.open = true; },
    close() { this.open = false; },
    querySelector(selector) { this.focusedSelector = selector; return { focus() {} }; },
  };
}

function setFormData(values) {
  const original = globalThis.FormData;
  globalThis.FormData = class {
    get(name) { return values[name] ?? null; }
  };
  return () => { globalThis.FormData = original; };
}

async function loadAccounts(ui) {
  await ui.flushEffects();
  ui.refresh();
}

test("directory loads the existing safe account fields and protects Super Admin edits", async () => {
  const calls = [];
  const ui = render(async (path, options) => { calls.push({ path, options }); return sampleAccounts; });
  await loadAccounts(ui);

  assert.equal(calls[0].path, "/api/users?q=&limit=20&offset=0");
  assert.ok(nodeBy(ui, "th", node => node.props.children === "Login"));
  assert.ok(nodeBy(ui, "th", node => node.props.children === "Display name"));
  assert.ok(nodeBy(ui, "strong", node => node.props.children === "adminemman"));
  assert.ok(ui.nodes.some(node => node.type === "span" && node.props.children === "Protected account"));
  assert.equal(ui.nodes.filter(node => node.type === "button" && nodeLabel(node) === "Edit").length, 2);
  assert.equal(ui.nodes.some(node => JSON.stringify(node.props).includes("password_hash")), false);
});

test("disabled status and first-login password requirement remain explicit", async () => {
  const disabledAccount = {
    id: 8,
    login_name: "synthetic-disabled",
    display_name: "Synthetic Disabled",
    role: "assistant_admin",
    is_enabled: false,
    password_change_required: true,
    updated_at: "2026-10-23T02:00:00Z",
  };
  const ui = render(async () => [disabledAccount]);
  await loadAccounts(ui);

  const statusComponents = ui.nodes.filter(node => node.type?.name === "AccountStatus");
  assert.ok(statusComponents.some(node => node.props.account.login_name === "synthetic-disabled"
    && !node.props.account.is_enabled && node.props.account.password_change_required));
  assert.ok(ui.nodes.some(node => node.type === "span" && typeof node.props.className === "string"
    && node.props.className.includes("users-role--assistant_admin")
    && node.props.children === "Assistant Admin"));
});

test("search uses the existing query contract and renders empty and loading states", async () => {
  const calls = [];
  const ui = render(async (path, options) => {
    calls.push({ path, options });
    return path.includes("q=missing") ? [] : sampleAccounts;
  });
  await loadAccounts(ui);

  const search = nodeBy(ui, "input", node => node.props.maxLength === 100);
  search.props.onChange({ target: { value: " missing " } });
  ui.refresh();
  const form = nodeBy(ui, "form", node => node.props["aria-label"] === "Search user accounts");
  form.props.onSubmit({ preventDefault() {} });
  ui.refresh();
  assert.ok(ui.nodes.some(node => node.props?.role === "status" && nodeLabel(node) === "Loading accounts…"));
  await ui.flushEffects();
  ui.refresh();

  assert.equal(calls.at(-1).path, "/api/users?q=missing&limit=20&offset=0");
  assert.ok(ui.nodes.some(node => node.props?.children === "No accounts match this search"));
});

test("listing failure is explicit and retryable rather than rendering stale rows", async () => {
  let fail = true;
  const ui = render(async () => {
    if (fail) throw new Error("The service is unavailable. Please try again.");
    return sampleAccounts;
  });
  await loadAccounts(ui);
  assert.ok(ui.nodes.some(node => node.props?.role === "alert" && nodeLabel(node).includes("The service is unavailable. Please try again.")));
  assert.equal(ui.nodes.some(node => node.props?.className === "users-table"), false);

  fail = false;
  nodeBy(ui, "button", node => nodeLabel(node) === "Retry").props.onClick();
  await ui.flushEffects();
  ui.refresh();
  assert.ok(nodeBy(ui, "table"));
});

test("create sends the existing contract, clears the password, and never confirms a secret", async () => {
  const calls = [];
  const ui = render(async (path, options) => {
    calls.push({ path, options });
    return path.startsWith("/api/users?") ? [] : undefined;
  });
  await loadAccounts(ui);

  const dialog = dialogDouble();
  ui.refs[0].current = dialog;
  const restore = setFormData({ login: "Synthetic", display: "Synthetic User", role: "admin", password: "synthetic-secret" });
  try {
    nodeBy(ui, "button", node => nodeLabel(node) === "Create user").props.onClick();
    ui.refresh();
    await ui.flushEffects();
    assert.equal(dialog.open, true);

    const { form, input } = passwordForm();
    const createForm = nodeBy(ui, "form", node => node.props["aria-label"] === "Create account");
    await createForm.props.onSubmit({ preventDefault() {}, currentTarget: form });
    ui.refresh();

    assert.equal(calls.find(call => call.path === "/api/users").options.body.temporary_password, "synthetic-secret");
    assert.equal(form.resetCalled, true);
    assert.equal(input.value, "");
    assert.ok(calls.some(call => call.path === "/api/users?q=&limit=20&offset=0"));
    assert.ok(ui.nodes.some(node => node.props?.role === "status" && node.props.children === "Account created. Share the temporary password privately."));
    assert.equal(JSON.stringify(ui.tree).includes("synthetic-secret"), false);
  } finally {
    restore();
  }
});

test("failed create shows the API error and clears the rejected temporary password", async () => {
  const ui = render(async path => {
    if (path === "/api/users") throw new Error("This action is not permitted.");
    return [];
  });
  await loadAccounts(ui);
  ui.refs[0].current = dialogDouble();
  const restore = setFormData({ login: "Synthetic", display: "Synthetic User", role: "admin", password: "synthetic-secret" });
  try {
    nodeBy(ui, "button", node => nodeLabel(node) === "Create user").props.onClick();
    ui.refresh();
    const { form, input } = passwordForm();
    await nodeBy(ui, "form", node => node.props["aria-label"] === "Create account")
      .props.onSubmit({ preventDefault() {}, currentTarget: form });
    ui.refresh();
    assert.equal(input.value, "");
    assert.ok(ui.nodes.some(node => node.props?.role === "alert" && node.props.children === "This action is not permitted."));
  } finally {
    restore();
  }
});

test("edit confirms the affected account and preserves the existing PATCH fields", async () => {
  const calls = [];
  const ui = render(async (path, options) => { calls.push({ path, options }); return sampleAccounts; });
  await loadAccounts(ui);

  const dialog = dialogDouble();
  ui.refs[0].current = dialog;
  const originalWindow = globalThis.window;
  let confirmation = "";
  globalThis.window = { confirm: message => { confirmation = message; return true; } };
  const restore = setFormData({ display: "Updated Name", role: "assistant_admin", enabled: "no", password: "synthetic-reset" });
  try {
    nodeBy(ui, "button", node => nodeLabel(node) === "Edit").props.onClick();
    ui.refresh();
    await ui.flushEffects();
    const { form, input } = passwordForm();
    const editForm = nodeBy(ui, "form", node => node.props["aria-label"] === "Edit account adminemman");
    await editForm.props.onSubmit({ preventDefault() {}, currentTarget: form });

    const update = calls.find(call => call.path === "/api/users/2");
    assert.match(confirmation, /role, account status, temporary password for adminemman/);
    assert.match(confirmation, /revoke existing sessions/);
    assert.equal(update.options.method, "PATCH");
    assert.equal(update.options.body.expected_updated_at, sampleAccounts[0].updated_at);
    assert.deepEqual(update.options.body, {
      expected_updated_at: sampleAccounts[0].updated_at,
      display_name: "Updated Name",
      role: "assistant_admin",
      is_enabled: false,
      temporary_password: "synthetic-reset",
    });
    assert.equal(input.value, "");
  } finally {
    restore();
    globalThis.window = originalWindow;
  }
});

test("edit cancellation does not issue a request and leaves the dialog available", async () => {
  const calls = [];
  const ui = render(async (path, options) => { calls.push({ path, options }); return sampleAccounts; });
  await loadAccounts(ui);
  ui.refs[0].current = dialogDouble();
  const originalWindow = globalThis.window;
  globalThis.window = { confirm: () => false };
  const restore = setFormData({ display: "Changed", role: "admin", enabled: "yes", password: "" });
  try {
    nodeBy(ui, "button", node => nodeLabel(node) === "Edit").props.onClick();
    ui.refresh();
    const { form } = passwordForm();
    await nodeBy(ui, "form", node => node.props["aria-label"] === "Edit account adminemman")
      .props.onSubmit({ preventDefault() {}, currentTarget: form });
    assert.equal(calls.some(call => call.path === "/api/users/2"), false);
  } finally {
    restore();
    globalThis.window = originalWindow;
  }
});

test("account dialogs focus the first field and close safely with Escape", async () => {
  const ui = render(async () => sampleAccounts);
  await loadAccounts(ui);
  const dialog = dialogDouble();
  ui.refs[0].current = dialog;
  nodeBy(ui, "button", node => nodeLabel(node) === "Edit").props.onClick();
  ui.refresh();
  await ui.flushEffects();
  assert.equal(dialog.focusedSelector, "[data-dialog-autofocus]");

  const escape = nodeBy(ui, "dialog").props.onKeyDown;
  let prevented = false;
  escape({ key: "Escape", preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(dialog.open, false);
});

test("pagination keeps the 20-account offset contract", async () => {
  const calls = [];
  const pageAccounts = Array.from({ length: 20 }, (_, index) => ({
    id: index + 1, login_name: `synthetic-${index + 1}`, display_name: `Synthetic ${index + 1}`,
    role: "admin", is_enabled: true, password_change_required: false, updated_at: "2026-10-23T02:00:00Z",
  }));
  const ui = render(async (path, options) => { calls.push({ path, options }); return pageAccounts; });
  await loadAccounts(ui);
  nodeBy(ui, "button", node => nodeLabel(node).includes("Next")).props.onClick();
  ui.refresh();
  await ui.flushEffects();
  ui.refresh();

  assert.ok(calls.some(call => call.path === "/api/users?q=&limit=20&offset=20"));
  assert.ok(ui.nodes.some(node => node.props?.["aria-current"] === "page" && nodeLabel(node) === "Page 2"));
  assert.equal(nodeBy(ui, "button", node => nodeLabel(node).includes("Previous")).props.disabled, false);
});

test("responsive directory exposes a compact labeled mobile account list", () => {
  const ui = render(async () => sampleAccounts);
  const sourceFile = source;
  assert.match(sourceFile, /className="users-mobile-list"/);
  assert.match(sourceFile, /<dt>Role<\/dt>/);
  assert.match(sourceFile, /<dt>Account status<\/dt>/);
  assert.ok(nodeBy(ui, "form", node => node.props["aria-label"] === "Search user accounts"));
});
