// Run with: node --test tests/test_archive_persistence.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const functions = source.slice(source.indexOf('function loadArchivedTrees()'), source.indexOf('function isTreeArchived('));
const mutation = source.slice(source.indexOf('async function setTreeArchived('), source.indexOf('function renderProjectsArchiveBar('));

function renderer(server, legacy = []) {
  const context = vm.createContext({
    isHubMode: () => false,
    console: { warn: () => {} },
    KoiApi: {
      getArchivedTrees: async () => {
        if (server.readFail) throw Error('404 Not Found');
        return { ids: server.ids };
      },
      saveArchivedTrees: async (ids) => {
        if (server.fail) throw Error('disk full');
        server.ids = ids;
      },
    },
    localStorage: { getItem: () => JSON.stringify(legacy) },
    window: { alert: () => {} },
    state: { project: null },
    loadProjectList: async () => {},
  });
  vm.runInContext(`const ARCHIVED_TREES_KEY = 'archive';
    let archivedTreeIds = null, archivedTreesReady = null, archiveSavePending = false;
    let projectsArchiveOpen = false;
    ${functions}\n${mutation}`, context);
  return (code) => vm.runInContext(code, context);
}

test('migration, renderer restart, unarchive, and failed save', async () => {
  const server = { ids: null };
  let run = renderer(server, ['a', 'composite:b']);
  await run('restoreArchivedTrees()');
  assert.deepEqual(Array.from(server.ids), ['a', 'composite:b']);
  run = renderer(server); // new renderer with empty localStorage, different origin
  await run('restoreArchivedTrees()');
  assert.equal(run('ensureArchivedTrees().has("a")'), true);
  await run('setTreeArchived("a", false)');
  assert.deepEqual(Array.from(server.ids), ['composite:b']);
  server.fail = true;
  await run('setTreeArchived("composite:b", false)');
  assert.equal(run('ensureArchivedTrees().has("composite:b")'), true);
  server.fail = false;
  await run('setTreeArchived("composite:b", false)');
  run = renderer(server, ['a']); // saved empty archive wins over stale legacy data
  await run('restoreArchivedTrees()');
  assert.equal(run('ensureArchivedTrees().size'), 0);
});


test('unavailable archive API cannot abort project loading and can recover', async () => {
  const server = { ids: ['saved'], readFail: true };
  const run = renderer(server, ['legacy']);
  assert.equal(await run('restoreArchivedTrees()'), false);
  assert.equal(run('ensureArchivedTrees().has("legacy")'), true);
  await run('setTreeArchived("new", true)');
  assert.deepEqual(server.ids, ['saved']);
  assert.equal(run('ensureArchivedTrees().has("new")'), false);
  server.readFail = false;
  assert.equal(await run('restoreArchivedTrees()'), true);
  assert.equal(run('ensureArchivedTrees().has("saved")'), true);
});

test('fresh install loads without requiring a settings write', async () => {
  const server = { ids: null, fail: true };
  const run = renderer(server);
  assert.equal(await run('restoreArchivedTrees()'), true);
  assert.equal(run('ensureArchivedTrees().size'), 0);
});
