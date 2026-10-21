// Run: node --test tests/test_card_live_tabs.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/card-live.js'), 'utf8')
  .replace('import { KoiApi } from "./api.js";', 'const KoiApi = {};').replaceAll('export ', '');
const ctx = vm.createContext({});
vm.runInContext(source, ctx);
test('highlight actual content, not configured or missing files', () => {
  const views = ctx.liveContentViews({metrics_dir: {configured: true, images: []}, live_note: '  ', live_log: {configured: true, tail: ''}, evo: {exists: false}});
  assert.equal(Object.values(views).some(Boolean), false);
  const populated = ctx.liveContentViews({metrics_dir: {images: [{name: 'loss.png'}]}, live_note: 'Training', live_log: {tail: 'step 10'}, evo: {exists: true}});
  for (const key of ['metrics', 'note', 'log']) assert.equal(populated[key], true);
  assert.equal("evo" in populated, false);
  assert.equal(ctx.cardHasLiveHints("evo_run: runs/evo/old-run"), false);
  assert.equal(Object.values(ctx.liveContentViews(null)).some(Boolean), false);
});

test('archived projects are excluded from seeds, discovery and already open tabs', async () => {
  const run = code => vm.runInContext(code, ctx);
  run(`var archived = new Set(['old']);
    setRunningSeedProvider(() => [], id => !archived.has(id));
    var project = {boards: [{id:'b', cards:[{id:'c', column_id:'running'}]}]};`);
  assert.equal(run('runningCardContextsFromProjects({old:project, current:project}).length'), 1);
  await run(`var monitorCalls = 0; KoiApi.getKanbanLiveMonitor = async () => { monitorCalls++; return {items:[]}; };
    syncRunningTabs({projectId:'old',boardId:'b',cardId:'c'})`);
  assert.equal(run('monitored.size'), 0);
  assert.equal(run('monitorCalls'), 0);
  run(`upsertMonitoredCard({projectId:'current',boardId:'b',cardId:'c'});
    pinnedKey = activeKey = 'current:b:c';
    archived.add('current'); pruneInactiveCards();`);
  assert.equal(run('monitored.size'), 0);
  assert.equal(run('activeKey'), null);
});

test('archiving a composite excludes its members without excluding unrelated projects', () => {
  const app = fs.readFileSync(require('node:path').join(__dirname, '../web/app.js'), 'utf8');
  const fn = app.slice(app.indexOf('function isMonitorProjectAllowed('), app.indexOf('function syncRunningSeedProvider('));
  const scope = vm.createContext({
    isTreeArchived: id => ['old', 'composite:group'].includes(id),
    compositeVirtualId: id => `composite:${id}`,
    state: {lab: {grouped: {groups: [{composites: [{id:'group',member_ids:['member']}]}]}}},
  });
  vm.runInContext(fn, scope);
  for (const id of ['old','composite:group','member']) assert.equal(scope.isMonitorProjectAllowed(id), false);
  assert.equal(scope.isMonitorProjectAllowed('current'), true);
});

test('tab indicator requires graphs, while comments and logs remain in the tooltip', () => {
  const tabs = {innerHTML: '', scrollLeft: 0, contains: () => false};
  const scope = vm.createContext({document: {getElementById: () => tabs}});
  vm.runInContext(source, scope);
  vm.runInContext(`
    upsertMonitoredCard({projectId:'p',boardId:'b',cardId:'c'});
    activeKey = 'p:b:c';
    monitored.get(activeKey).data = {live_note:'Training', live_log:{tail:'step 1'}};
    renderCardTabs();`, scope);
  assert.ok(!tabs.innerHTML.includes('has-content'));
  assert.ok(tabs.innerHTML.includes('Комментарий · Логи'));
  vm.runInContext(`monitored.get(activeKey).data.metrics_dir = {images:[{name:'loss.png'}]}; renderCardTabs();`, scope);
  assert.ok(tabs.innerHTML.includes('has-content'));
  vm.runInContext(`monitored.get(activeKey).data.metrics_dir.images = []; renderCardTabs();`, scope);
  assert.ok(!tabs.innerHTML.includes('has-content'));
});
