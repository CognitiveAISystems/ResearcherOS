const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const projectId = source.slice(source.indexOf('function agentChatProjectId()'), source.indexOf('function resizeAgentChatInput()'));

test('selected conversation retains its project when the map changes; global chat does not inherit active project', () => {
  const context = vm.createContext({ mainConversations: { row: { project_id: 'chat-project' } }, primaryMemberProjectId: () => 'map-project' });
  vm.runInContext(projectId, context);
  assert.equal(vm.runInContext('agentChatProjectId()', context), 'chat-project');
  context.mainConversations.row = null;
  assert.equal(vm.runInContext('agentChatProjectId()', context), null);
  context.mainConversations.row = {project_id: null};
  assert.equal(vm.runInContext('agentChatProjectId()', context), null);
  context.mainConversations.row = null; context.mainConversations.currentProjectOnly = true;
  assert.equal(vm.runInContext('agentChatProjectId()', context), 'map-project');
});

test('late responses cannot replace the newly selected conversation', async () => {
  const module = await import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync('web/chat-conversations.js')).toString('base64'));
  const deferred = {};
  const controller = Object.create(module.ChatConversations.prototype);
  Object.assign(controller, { epoch: 0, main: true, currentProjectOnly: false, row: {id: 'first'}, rows: [], drafts: new Map(), input: {value: ''},
    scope: () => ({project_id: 'a'}), render: () => {},
    api: { listConversations: async () => ({items: [{id: 'first'}, {id: 'second'}]}), getConversation: id => new Promise(resolve => deferred[id] = resolve) } });
  const first = controller.refresh();
  await new Promise(setImmediate);
  controller.row = {id: 'second'}; controller.epoch++;
  const second = controller.refresh();
  await new Promise(setImmediate);
  deferred.second({conversation: {id: 'second'}, items: [{id: 'correct'}]});
  assert.equal((await second).items[0].id, 'correct');
  deferred.first({conversation: {id: 'first'}, items: [{id: 'stale'}]});
  assert.equal(await first, null);
  assert.equal(controller.row.id, 'second');
});
