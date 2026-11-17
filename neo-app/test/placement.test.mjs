import assert from 'node:assert/strict';
import { test } from 'node:test';

import { placeAnchored } from '../src/lib/menuPlacement.js';

/** 팝업 요소 흉내: 크기와 style 만 있으면 된다. */
function fakePopup(width, height) {
  return { offsetWidth: width, offsetHeight: height, style: {} };
}
function fakeAnchor(left, top, width, height) {
  return {
    getBoundingClientRect: () => ({ left, top, right: left + width, bottom: top + height, width, height }),
  };
}
function withViewport(width, height, run) {
  const before = globalThis.window;
  globalThis.window = { innerWidth: width, innerHeight: height };
  try {
    run();
  } finally {
    globalThis.window = before;
  }
}
const px = (value) => Number.parseFloat(value);

test('단추 아래·왼쪽 맞춤이 기본', () => {
  withViewport(1000, 700, () => {
    const el = fakePopup(200, 100);
    placeAnchored(el, fakeAnchor(100, 50, 60, 28), 'bottom', 6);
    assert.equal(px(el.style.left), 100);
    assert.equal(px(el.style.top), 50 + 28 + 6);
    assert.equal(el.style.position, 'fixed');
  });
});

test('오른쪽이 모자라면 단추 오른쪽 끝에 맞춘다 (잘림 방지)', () => {
  withViewport(1000, 700, () => {
    const el = fakePopup(300, 100);
    placeAnchored(el, fakeAnchor(900, 50, 60, 28), 'bottom', 6);
    assert.equal(px(el.style.left), 960 - 300);
    assert.ok(px(el.style.left) + 300 <= 1000 - 6);
  });
});

test('단추 자체가 화면 끝이어도 팝업은 화면 안으로 밀린다', () => {
  withViewport(400, 700, () => {
    const el = fakePopup(380, 100);
    placeAnchored(el, fakeAnchor(350, 50, 40, 28), 'bottom', 6);
    assert.ok(px(el.style.left) >= 6);
    assert.ok(px(el.style.left) + 380 <= 400 - 6);
  });
});

test('아래가 모자라고 위가 넉넉하면 위로 뒤집는다', () => {
  withViewport(1000, 400, () => {
    const el = fakePopup(200, 150);
    placeAnchored(el, fakeAnchor(100, 330, 60, 28), 'bottom', 6);
    assert.equal(px(el.style.top), 330 - 6 - 150);
    assert.equal(el.style.maxHeight, '');
  });
});

test('위아래 모두 모자라면 넓은 쪽에 맞춰 줄이고 스크롤', () => {
  withViewport(1000, 300, () => {
    const el = fakePopup(200, 600);
    placeAnchored(el, fakeAnchor(100, 40, 60, 28), 'bottom', 6);
    const top = px(el.style.top);
    const maxHeight = px(el.style.maxHeight);
    assert.equal(el.style.overflowY, 'auto');
    assert.ok(top >= 6);
    assert.ok(top + maxHeight <= 300 - 6 + 0.001);
  });
});

test('하위 메뉴는 오른쪽에 열리고, 모자라면 왼쪽으로 뒤집힌다', () => {
  withViewport(1000, 700, () => {
    const roomy = fakePopup(220, 200);
    placeAnchored(roomy, fakeAnchor(100, 100, 224, 30), 'right', 2);
    assert.equal(px(roomy.style.left), 100 + 224 + 2);

    const tight = fakePopup(220, 200);
    placeAnchored(tight, fakeAnchor(700, 100, 224, 30), 'right', 2);
    assert.equal(px(tight.style.left), 700 - 2 - 220);
  });
});

test('하위 메뉴가 아래로 넘치면 위로 올려 맞춘다', () => {
  withViewport(1000, 500, () => {
    const el = fakePopup(220, 300);
    placeAnchored(el, fakeAnchor(100, 400, 224, 30), 'right', 2);
    assert.ok(px(el.style.top) + 300 <= 500 - 6);
    assert.ok(px(el.style.top) >= 6);
  });
});
