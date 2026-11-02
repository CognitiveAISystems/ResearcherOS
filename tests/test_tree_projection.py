"""Compatibility projection must preserve source IDs/data and edge ownership."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_legacy_tree_projection():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is needed for the frontend projection test')
    module = Path(__file__).resolve().parents[1] / 'web/tree-projection.js'
    script = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
const { projectTreeNodes } = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[1]).toString('base64'));
for (const kind of ['remediation', 'cause_evidence']) {
  for (const count of [0, 1, 2]) {
    const nodes = [
      {id:'p', node_type:'problem', parent_id:null},
      {id:'c', node_type:'cause', parent_id:'p', verdict:'supported'},
      {id:'h', node_type:kind, parent_id:'c', title:'Original claim', description:'Report links'},
      ...Array.from({length:count}, (_, i) => ({id:`m${i}`, node_type:'method', parent_id:'h', board_id:`b${i}`}))
    ];
    const before = JSON.stringify(nodes);
    const view = projectTreeNodes(nodes);
    assert.equal(JSON.stringify(nodes), before);
    assert.equal(view.find(n => n.id === 'c'), undefined);
    assert.equal(view.find(n => n.id === 'p').node_type, 'problem');
    const target = view.find(n => n.id === (count === 1 ? 'm0' : 'h'));
    assert.equal(target.parent_id, 'p');
    assert.equal(target.edge_label, 'Original claim');
    assert.equal(target.edge_source, nodes[2]);
    assert.equal(target.edge_type, kind === 'remediation' ? 'hypothesis' : 'evidence');
    assert.equal(view.filter(n => n.node_type === 'program').length, count === 1 ? 0 : 1);
    for (let i=0; i<count; i++) assert.equal(view.find(n => n.id === `m${i}`).board_id, `b${i}`);
  }
}
'''
    subprocess.run([node, '--input-type=module', '-e', script, str(module)], check=True)
