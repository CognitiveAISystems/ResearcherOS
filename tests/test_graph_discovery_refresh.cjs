// Run: node --test tests/test_graph_discovery_refresh.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
for (const file of ['web/app.js', 'web/variants/light/app.js']) {
  test(`${file}: external graph edits redraw and failed loads retry`, async () => {
    const source = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
    const fresh = {id: 'sample', nodes: [{id: 'new-node'}]};
    const revisions = [], renders = [];
    let fail = true;
    const scope = vm.createContext({
      projectDiscoveryRevision: 0,
      state: {project: {id: 'sample'}, lab: {}},
      KoiApi: {getProjectDiscovery: async since => {
        revisions.push(since);
        return {ok: true, revision: 1, changes: {changed: [{id: 'sample'}]}};
      }},
      loadLab: async () => {
        if (fail) throw new Error('temporary failure');
        scope.state.lab.projectsById = {sample: fresh};
      },
      loadProjectList: async () => {}, setActiveProjectInList: () => {},
      renderLabMindmap: options => renders.push(options),
      getViewMode: () => 'chief', console: {warn() {}},
    });
    vm.runInContext(source.slice(source.indexOf('async function refreshProjectDiscovery()'),
      source.indexOf('\nfunction initProjectDiscoveryPoll()')), scope);
    await scope.refreshProjectDiscovery();
    assert.equal(scope.projectDiscoveryRevision, 0);
    fail = false;
    await scope.refreshProjectDiscovery();
    assert.deepEqual(revisions, [0, 0]);
    assert.equal(scope.state.project, fresh);
    assert.equal(scope.projectDiscoveryRevision, 1);
    assert.equal(renders.length, 1);
    assert.equal(renders[0].fitLab, false);
  });
}
