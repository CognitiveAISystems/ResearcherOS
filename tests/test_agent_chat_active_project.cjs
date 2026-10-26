const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const projectId = source.slice(source.indexOf('function agentChatProjectId()'), source.indexOf('function resizeAgentChatInput()'));
const scope = source.slice(source.indexOf('function updateAgentChatScope()'), source.indexOf('function toggleAgentChatPanel('));
const refresh = source.slice(source.indexOf('async function refreshAgentChat('), source.indexOf('async function refreshAgentChatActivity()'));

test('open chat follows active project immediately and ignores late replies from the previous project', async () => {
  const pending = {};
  const elements = {
    'agent-chat-scope': {},
    'agent-chat-panel': { classList: { contains: () => false } },
    'agent-chat-activity': { textContent: '', classList: { contains: () => true } },
  };
  const context = vm.createContext({
    document: { getElementById: id => elements[id] },
    primaryMemberProjectId: () => context.activeId,
    agentChatContext: () => ({ label: null }),
    renderAgentChatLog: () => {}, syncAgentChatPolling: () => {},
    KoiApi: { listAgentChat: id => new Promise(resolve => { pending[id] = resolve; }) },
    activeId: 'first',
  });
  vm.runInContext(`let agentChatDisplayedProjectId = null, agentChatItems = []; ${projectId} ${scope} ${refresh}`, context);
  vm.runInContext('updateAgentChatScope()', context);
  context.activeId = 'second';
  vm.runInContext('updateAgentChatScope()', context);
  assert.deepEqual(Object.keys(pending), ['first', 'second']);
  pending.second({ items: [{ id: 'second-message' }] });
  await new Promise(setImmediate);
  pending.first({ items: [{ id: 'old-message' }] });
  await new Promise(setImmediate);
  assert.equal(vm.runInContext('agentChatItems[0].id', context), 'second-message');
  assert.equal(vm.runInContext('agentChatProjectId()', context), 'second');
});
