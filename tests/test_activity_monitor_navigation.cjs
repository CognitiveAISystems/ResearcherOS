// Run: node --test tests/test_activity_monitor_navigation.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

for (const file of ['web/app.js', 'web/variants/light/app.js']) {
  test(`${file}: each overlay monitor opens its own project, board and card`, () => {
    const buttons = ['card-a', 'card-b'].map(cardId => ({
      dataset: {cardId},
      addEventListener(event, handler) { this.click = handler; },
    }));
    const pins = buttons.map(button => ({querySelectorAll: () => [button]}));
    const items = ['a', 'b'].map(id => ({projectId: id, node: {id, title: id}}));
    const projects = Object.fromEntries(items.map(item => [item.projectId, {id: item.projectId}]));
    const opened = [];
    const scope = vm.createContext({
      document: {getElementById: id => id === 'method-activity-overlay'
        ? {children: pins, querySelectorAll: () => buttons} : {}},
      labCamera: {}, state: {lab: {projectsById: projects}}, cardLiveUi: {},
      collectRunningActivityItems: () => items,
      shouldUseActivityOverlay: () => true, syncMethodActivityOverlay: () => true,
      syncMethodActivityZoomMode: () => {}, isHubMode: () => false,
      nodeWriteProjectId: () => null,
      getBoardForNode: project => ({id: `board-${project.id}`, cards: [
        {id: `card-${project.id}`, title: project.id, column_id: 'running'},
      ]}),
      openCardLiveDrawer: ctx => opened.push(ctx),
    });
    const live = read('web/card-live.js');
    vm.runInContext(live.slice(live.indexOf('export function bindLiveInspectButtons')).replace('export ', ''), scope);
    const app = read(file);
    for (const [start, end] of [
      ['function bindMethodLiveInspect(', 'async function ensureRunningAuthors('],
      ['function syncLabActivityOverlay(', 'function refreshMethodActivityAuthors('],
    ]) vm.runInContext(app.slice(app.indexOf(start), app.indexOf(end)), scope);
    scope.syncLabActivityOverlay();
    buttons.forEach(button => button.click({preventDefault() {}, stopPropagation() {}}));
    assert.deepEqual(opened.map(ctx => [ctx.projectId, ctx.boardId, ctx.cardId]), [
      ['a', 'board-a', 'card-a'], ['b', 'board-b', 'card-b'],
    ]);
  });
}

test('replacing a running card invalidates overlay buttons even when the count stays the same', () => {
  const scope = vm.createContext({});
  vm.runInContext(read('web/method-activity.js').replaceAll('export ', ''), scope);
  const item = {key: 'project:method', state: {running: [{id: 'old'}]}};
  const before = scope.overlayItemsSignature([item]);
  item.state.running = [{id: 'new'}];
  assert.notEqual(scope.overlayItemsSignature([item]), before);
});
