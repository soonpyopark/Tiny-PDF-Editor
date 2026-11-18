import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildStandaloneHtml,
  formatJsonText,
  htmlSourceToPrintableHtml,
  isHtmlPath,
  isTextPath,
  renderMarkdown,
  textFileToHtml,
} from '../electron/textPdfHtml.mjs';

test('renderMarkdown strips markers and keeps structure', () => {
  const html = renderMarkdown('# 제목\n\n일반 **굵게** 와 `코드`\n\n- 첫\n- 둘\n\n> 인용\n');
  assert.match(html, /<h1>제목<\/h1>/);
  assert.match(html, /<strong>굵게<\/strong>/);
  assert.match(html, /<code>코드<\/code>/);
  assert.match(html, /<li>첫<\/li>/);
  assert.match(html, /<blockquote>/);
  assert.doesNotMatch(html, /\*\*굵게\*\*/);
  assert.doesNotMatch(html, /# 제목/);
});

test('buildStandaloneHtml wraps body with export CSS', () => {
  const doc = buildStandaloneHtml('<p>hello</p>', 'note');
  assert.match(doc, /<!DOCTYPE html>/);
  assert.match(doc, /markdown-export/);
  assert.match(doc, /Malgun Gothic/);
  assert.match(doc, /<p>hello<\/p>/);
  assert.match(doc, /<title>note<\/title>/);
});

test('html and text path detection', () => {
  assert.equal(isHtmlPath('a.html'), true);
  assert.equal(isHtmlPath('a.HTM'), true);
  assert.equal(isTextPath('a.md'), true);
  assert.equal(isTextPath('a.json'), true);
  assert.equal(isTextPath('a.html'), true);
  assert.equal(isTextPath('a.pdf'), false);
});

test('formatJsonText pretty-prints valid JSON', () => {
  assert.equal(formatJsonText('{"a":1}'), '{\n  "a": 1\n}');
  assert.equal(formatJsonText('not-json'), 'not-json');
  const html = textFileToHtml('note.json', '{"x":true}');
  assert.match(html, /&quot;x&quot;: true/);
});

test('htmlSourceToPrintableHtml injects base and keeps body', () => {
  const out = htmlSourceToPrintableHtml(
    'D:/docs/sample.html',
    '<!DOCTYPE html><html><head><title>x</title></head><body><h1>Hi</h1></body></html>',
  );
  assert.match(out, /<base href="/);
  assert.match(out, /@page/);
  assert.match(out, /<h1>Hi<\/h1>/);
});
