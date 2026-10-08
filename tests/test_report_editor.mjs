import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reportBlocks, applySetup, setupWouldShrink, EMPTY_REPORT } from '../web/report-editor.js';

test('Markdown survives block splitting without changing code, tables or references', () => {
  const source = '# Title\n\n## Цель\n\nText [link][id].\n\n```md\n## Результаты\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n[id]: https://example.org\n';
  assert.equal(reportBlocks(source).map(b => b.raw).join(''), source);
});
test('applying setup replaces only setup sections and preserves results and unknown sections', () => {
  const results = '## Эксперименты\n\nrun 1\n\n## Результаты\n\nSR=0.8\n\n## Appendix\n\nKeep me\n';
  const source = 'compute_cost: gpu_h=1\n\n## Цель\n\nOld\n\n## Постановка эксперимента\n\nOld protocol\n\n## Задачи\n\n- [x] Old\n\n' + results;
  const proposal = {goal:'New',setup:'Protocol\n\n```md\n## Результаты\n```',tasks:'- [ ] Eval'};
  const applied = applySetup(source, proposal);
  assert.ok(applied.endsWith(results));
  assert.ok(applied.startsWith('compute_cost: gpu_h=1\n\n'));
  assert.ok(!applied.includes('Old'));
  assert.equal(applySetup(applied, proposal), applied);
});
test('empty document gets the five sections and setup does not invent results', () => {
  const result = applySetup(EMPTY_REPORT, {goal:'Claim',setup:'Control',tasks:'- [ ] Test'});
  assert.equal((result.match(/^## /gm)||[]).length, 5);
  assert.ok(result.endsWith('## Эксперименты\n\n## Результаты\n'));
});
test('warns when a detailed setup would be replaced by a short summary', () => {
  const detail = 'Control and protocol details. '.repeat(12);
  const source = `## Постановка эксперимента\n\n${detail}\n\n## Задачи\n\n- [ ] Test\n`;
  assert.equal(setupWouldShrink(source, {setup: 'Brief summary'}), true);
  assert.equal(setupWouldShrink(source, {setup: detail}), false);
  assert.equal(setupWouldShrink(EMPTY_REPORT, {setup: 'Brief summary'}), false);
});
