import test from 'node:test';
import assert from 'node:assert/strict';
import {renderMarkdown} from '../web/markdown.js';

test('TeX is parsed before Markdown changes indices and backslashes', () => {
  const html = renderMarkdown(String.raw`$x_i + y_j$ и \(\frac{a}{b}\)`);
  assert.equal((html.match(/<math /g) || []).length, 2);
  assert.match(html, /<msub>/);
  assert.match(html, /<mfrac>/);
  assert.doesNotMatch(html, /<em>/);
});

test('display delimiters support multiline aligned equations', () => {
  for (const source of [String.raw`$$
\begin{aligned}x &= 1 \\ y &= 2\end{aligned}
$$`, String.raw`\[\sum_{i=1}^{n} i\]`]) {
    const html = renderMarkdown(source);
    assert.match(html, /md-math-display/);
    assert.match(html, /display="block"/);
    assert.doesNotMatch(html, /katex-error/);
  }
});

test('code, escaped dollars, prices and unfinished formulas stay literal', () => {
  for (const source of ['`$x_i$`', '```tex\n$x_i$\n```', String.raw`\$x\$`, 'Цена $5 и $10', '$unfinished']) {
    assert.doesNotMatch(renderMarkdown(source), /<math /);
  }
});

test('invalid TeX remains visible and cannot inject HTML', () => {
  const html = renderMarkdown(String.raw`$\unknown{<img src=x onerror=alert(1)>}$`);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /unknown/);
});
