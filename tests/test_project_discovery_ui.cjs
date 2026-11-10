const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');

for (const file of ['web/app.js', 'web/variants/light/app.js']) {
  for (const scenario of ['added card', 'changed status', 'unchanged board', 'closed board', 'failed refresh']) {
    test(`${file}: discovery refresh — ${scenario}`, async () => {
      const board = { id: 'board', cards: [{ id: 'existing', column_id: 'backlog' }] };
      const node = { id: 'method', board_id: board.id };
      const project = { id: 'project', nodes: [node], boards: { board } };
      const updated = structuredClone(project);
      if (scenario === 'added card') updated.boards.board.cards.push({ id: 'agent-card', column_id: 'backlog' });
      if (scenario === 'changed status') updated.boards.board.cards[0].column_id = 'running';
      const renders = [];
      const context = vm.createContext({
        state: { project, kanbanNodeId: node.id },
        projectDiscoveryRevision: 0,
        KoiApi: { getProjectDiscovery: async () => ({ ok: true, revision: 1, changes: { changed: [{ id: project.id }] } }) },
        loadLab: async () => {
          if (scenario === 'failed refresh') throw new Error('offline');
          context.state.lab = { projectsById: { project: updated } };
        },
        loadProjectList: async () => {},
        setActiveProjectInList() {},
        renderLabMindmap() {},
        getViewMode: () => 'researcher',
        getBoardForNode: (p, n) => p.boards[n.board_id],
        isKanbanModalOpen: () => scenario !== 'closed board',
        renderActiveKanbanView: (b, n) => renders.push({ board: b, node: n }),
        console: { warn() {} },
      });
      const source = readFileSync(file, 'utf8');
      const start = source.indexOf('async function refreshProjectDiscovery()');
      const end = source.indexOf('\nfunction initProjectDiscoveryPoll()', start);
      vm.runInContext(source.slice(start, end), context);
      await context.refreshProjectDiscovery();
      const shouldRender = ['added card', 'changed status'].includes(scenario);
      assert.equal(renders.length, shouldRender ? 1 : 0);
      if (shouldRender) assert.deepEqual(renders[0], { board: updated.boards.board, node: updated.nodes[0] });
      assert.equal(context.projectDiscoveryRevision, scenario === 'failed refresh' ? 0 : 1);
    });
  }
}
