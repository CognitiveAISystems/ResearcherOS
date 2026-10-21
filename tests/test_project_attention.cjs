const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('web/project-attention.js', 'utf8').replaceAll('export ', '') +
  '\nthis.Model = ProjectAttention; this.proximity = projectProximity;', context);
const { Model, proximity } = context;

test('explicit work wins, old history decays and a stable centered tree takes over', () => {
  const m = new Model();
  for (let t = 0; t < 8; t++) m.interact('a', { a: 1, b: 0.1 }, t * 100);
  assert.equal(m.choose('a', { a: 0.05, b: 0.59 }, 2000), 'a');
  assert.equal(m.choose('a', { a: 0.05, b: 0.59 }, 240000), 'a');
  assert.equal(m.choose('a', { a: 0.05, b: 0.59 }, 240800), 'b');
});

test('fast flyovers, ties, empty space and edge-only nodes keep current context', () => {
  const m = new Model();
  assert.equal(m.choose('a', { b: 0.55 }, 0), 'a');
  assert.equal(m.choose('a', { c: 0.55 }, 500), 'a');
  assert.equal(m.choose('a', { b: 0.55 }, 1000), 'a');
  assert.equal(m.choose('a', { a: 1, b: 1 }, 2000), 'a');
  assert.equal(m.choose('a', {}, 3000), 'a');
  assert.equal(m.choose('a', { b: 0.1 }, 4000), 'a');
});

test('explicit intent interrupts a pending switch and history is bounded', () => {
  const m = new Model();
  m.choose('a', { b: 0.55 }, 0);
  m.interact('a', { a: 0.05, b: 0.59 }, 500);
  assert.equal(m.choose('a', { b: 0.55 }, 1000), 'a');
  for (let i = 0; i < 20; i++) m.interact('a', { a: 1 }, 2000 + i);
  assert.equal(m.history.length, 8);
});

test('shadow learning uses pre-action features and cannot alter production decisions', () => {
  const m = new Model();
  m.interact('b', { a: 1, b: 0.1 }, 0);
  assert.equal(m.metrics.baselineMatches, 0);
  assert.equal(m.metrics.learnedMatches, 0);
  const baseline = m.choose('a', { b: 0.55 }, 100000);
  m.weights = [1, 0];
  m.reset();
  assert.equal(m.choose('a', { b: 0.55 }, 100000), baseline);
  assert.equal(m.choose('a', { b: 0.55 }, 100800), 'b');
});

test('visible branches count even with offscreen root; hidden nodes and tree size do not bias focus', () => {
  const rect = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height });
  const scores = proximity([
    { id: 'a', rect: rect(-1000, -1000, 100, 50) },
    { id: 'a', rect: rect(450, 450, 100, 100) },
    { id: 'b', rect: rect(900, 450, 50, 50) },
    { id: 'hidden', rect: rect(500, 500, 0, 0) },
  ], rect(0, 0, 1000, 1000));
  assert.equal(scores.a, 1);
  assert.ok(scores.b < 0.2);
  assert.equal(scores.hidden, undefined);
});

 test('zoom focus immediately overrides recent history, including while old tree is still at the edge', () => {
  const m = new Model();
  for (let i = 0; i < 8; i++) m.interact('a', { a: 1, b: 0.1 }, i);
  assert.equal(m.choose('a', { a: 0.2, b: 0.95 }, 10), 'b');
  assert.equal(m.choose('a', { b: 0.95 }, 11), 'b');
  assert.equal(m.choose('b', { a: 0.95, b: 0.2 }, 12), 'a');
});
