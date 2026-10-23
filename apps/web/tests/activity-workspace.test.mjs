import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

function render({page = null, error = '', loading = false, history = []} = {}) {
  let i = 0; const updates = [];
  const states = ['', null, history, page, error, loading];
  const react = {useState: () => { const index = i++; return [states[index], value => updates.push([index, value])]; }, useEffect: () => {}};
  const jsx = (type, props) => ({type, props: props ?? {}});
  const source = readFileSync(new URL('../src/components/activity-workspace.tsx', import.meta.url), 'utf8');
  const code = ts.transpileModule(source, {compilerOptions:{jsx:ts.JsxEmit.ReactJSX, module:ts.ModuleKind.CommonJS}}).outputText;
  const exports = {}; new Function('require','exports',code)(name => name === 'react' ? react : {jsx, jsxs:jsx}, exports);
  const tree = exports.default({request: () => {}}); const nodes = [];
  function visit(node) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) return node.forEach(visit);
    if (typeof node.type === 'function') return visit(node.type(node.props));
    nodes.push(node);
    visit(node.props.children);
  }
  visit(tree); return {nodes, updates};
}

test('activity filters validate dates and pass supported values', () => {
  const ui = render(); const form = ui.nodes.find(node => node.type === 'form');
  const original = globalThis.FormData;
  globalThis.FormData = class { get(name) { return {start:'2026-01-01', end:'2026-01-31', action:'dish_updated', entity:'dishes', reference:'88'}[name] ?? ''; } };
  try { form.props.onSubmit({preventDefault(){},currentTarget:{}}); assert.ok(ui.updates.some(([i,v]) => i === 0 && v.includes('action=dish_updated') && v.includes('reference=88'))); }
  finally { globalThis.FormData = original; }
});

test('activity ledger presents safe event details, PHT timestamps and cursor navigation', () => {
  const page = {items:[{id:1,occurred_at:'2026-01-01T04:00:00Z',actor_id:4,actor_display_name:'Synthetic',action:'user_role_changed',entity_type:'users',reference:'88',before:{role:'admin'},after:{role:'assistant_admin'},reason:null}],next_cursor:'next'};
  const ui = render({page});
  assert.ok(ui.nodes.some(n => n.type === 'h4' && n.props.children === 'Role changed'));
  assert.ok(ui.nodes.some(n => n.type === 'span' && n.props.children === 'View safe details'));
  assert.ok(ui.nodes.some(n => n.type === 'dt' && n.props.children === 'Role'));
  assert.ok(ui.nodes.some(n => n.type === 'dd' && n.props.children === 'Admin'));
  assert.ok(ui.nodes.some(n => n.type === 'dd' && n.props.children === 'Assistant Admin'));
  assert.ok(ui.nodes.some(n => n.type === 'span' && n.props.className === 'activity-icon activity-icon--role' && n.props['data-icon'] === 'role'));
  assert.ok(ui.nodes.some(n => n.type === 'time' && n.props.dateTime === '2026-01-01T04:00:00Z'));
  assert.ok(ui.nodes.some(n => n.type === 'ol' && n.props['aria-label'] === 'Activity event ledger'));
  assert.ok(ui.nodes.some(n => n.type === 'nav' && n.props['aria-label'] === 'Activity log pages'));
  const next = ui.nodes.find(n => n.type === 'button' && Array.isArray(n.props.children)
    && n.props.children.some(child => typeof child === 'string' && child.trim() === 'Next'));
  assert.equal(next.props.disabled, false); next.props.onClick();
  assert.ok(ui.updates.some(([i,v]) => i === 1 && v === 'next'));
});

test('activity maps received status changes and approved correction reasons', () => {
  const page = {items:[{id:2,occurred_at:'2026-01-02T04:00:00Z',actor_id:4,actor_display_name:'Synthetic',action:'received_reversed',entity_type:'orders',reference:'88',before:{is_received:true},after:{is_received:false},reason:'Mistaken click'}],next_cursor:null};
  const ui = render({page});
  assert.ok(ui.nodes.some(node => node.type === 'h4' && node.props.children === 'Received reversed'));
  assert.ok(ui.nodes.some(node => node.type === 'dt' && node.props.children === 'Order status'));
  assert.ok(ui.nodes.some(node => node.type === 'dd' && node.props.children === 'Received'));
  assert.ok(ui.nodes.some(node => node.type === 'dd' && node.props.children === 'Pending'));
  assert.ok(ui.nodes.some(node => node.type === 'strong' && node.props.children === 'Correction reason'));
  assert.ok(ui.nodes.some(node => node.type === 'span' && node.props.children === 'Mistaken click'));
});

test('activity maps recorded action families to consistent icons with a neutral fallback', () => {
  const actions = [
    ['order_created', 'order'], ['order_edited', 'edit'], ['received_marked', 'received'],
    ['received_reversed', 'reversed'], ['menu_created', 'menu'], ['dish_updated', 'dish'],
    ['visitor_created', 'visitor'], ['employee_import_completed', 'import'],
    ['user_created', 'user'], ['user_role_changed', 'role'], ['user_disabled', 'disabled'],
    ['user_reactivated', 'enabled'], ['user_password_reset', 'password'],
    ['password_changed', 'password'], ['super_admin_promoted', 'admin'],
    ['first_admin_provisioned', 'admin'], ['auth_login', 'auth'], ['auth_logout', 'auth'],
    ['future_event', 'neutral'],
  ];
  const page = {items: actions.map(([action], index) => ({
    id:index + 1, occurred_at:'2026-01-01T04:00:00Z', actor_id:4, actor_display_name:'Synthetic',
    action, entity_type:null, reference:null, before:{}, after:{}, reason:null,
  })),next_cursor:null};
  const ui = render({page});
  const icons = ui.nodes.filter(node => node.props.className?.startsWith('activity-icon '));
  assert.deepEqual(icons.map(node => [node.props['data-icon'], node.props.className.split('--')[1]]),
    actions.map(([, expected]) => [expected, expected]));
  assert.ok(ui.nodes.some(node => node.type === 'h4' && node.props.children === 'Unknown event'));
});

test('activity filters retain supported fields and semantic keyboard controls', () => {
  const ui = render();
  const form = ui.nodes.find(node => node.type === 'form');
  assert.equal(form.props['aria-label'], 'Filter activity logs');
  for (const name of ['start', 'end', 'actor_id', 'action', 'entity', 'reference']) {
    assert.ok(ui.nodes.some(node => ['input', 'select'].includes(node.type) && node.props.name === name));
    assert.ok(ui.nodes.some(node => node.type === 'label' && node.props.children[0] === nameLabel(name)));
  }
  assert.ok(ui.nodes.some(node => node.type === 'button' && node.props.children === 'Apply filters'));
});

function nameLabel(name) {
  return ({start:'From', end:'To', actor_id:'Actor user ID', action:'Action', entity:'Entity', reference:'Reference'})[name];
}

test('activity displays loading, empty and error states', () => {
  assert.ok(render({loading:true}).nodes.some(n => n.props.role === 'status' && n.props.className === 'activity-state activity-state--loading'));
  assert.ok(render({page:{items:[],next_cursor:null}}).nodes.some(n => n.type === 'strong' && n.props.children === 'No activity matches these filters'));
  assert.ok(render({error:'Permission denied'}).nodes.some(n => n.props.role === 'alert' && n.props.className === 'activity-error'));
});
