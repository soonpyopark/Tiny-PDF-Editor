import assert from 'node:assert/strict';
import { extractChanges, extractPriorHistory, releaseBody } from './publish-release.mjs';

const prev = {
  name: 'v1.0.0.8',
  tagName: 'v1.0.0-8',
  body: `## 변경
- 진행 카드
- WebP 지원

## 파일
- a.msi
- b.zip
`,
};

const withHistory = {
  name: 'v1.0.0.8',
  tagName: 'v1.0.0-8',
  body: `## 변경
- 여덟

## 파일
- a.msi

## 이전 버전 이력

### v1.0.0.7
- 일곱
`,
};

assert.equal(extractChanges(prev.body), '- 진행 카드\n- WebP 지원');
assert.equal(extractPriorHistory(prev.body), '');
assert.equal(extractPriorHistory(withHistory.body), '### v1.0.0.7\n- 일곱');

const body = releaseBody('- 아홉', ['x.msi'], prev);
assert.match(body, /^## 변경\n- 아홉\n/);
assert.match(body, /## 파일\n- x\.msi\n/);
assert.match(body, /## 이전 버전 이력\n\n### v1.0.0\.8\n- 진행 카드\n- WebP 지원\n/);
assert.doesNotMatch(body, /a\.msi/);

const chained = releaseBody('- 아홉', ['x.msi'], withHistory);
assert.match(chained, /### v1.0.0\.8\n- 여덟\n/);
assert.match(chained, /### v1.0.0\.7\n- 일곱\n/);

assert.equal(releaseBody('- only', ['f.zip'], null).includes('이전 버전 이력'), false);

console.log('publish-release-notes.test.mjs: ok');
