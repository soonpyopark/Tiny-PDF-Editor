import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildPrintHtml,
  dpiForSheets,
  layoutSheets,
  nearestPaperId,
  normalizePrintOptions,
  parsePageRange,
  renderZoomFor,
} from '../shared/printLayout.js';

const A4 = [595.28, 841.89];
const A4_LAND = [841.89, 595.28];

test('범위 글을 0 기반 쪽 번호로 바꾼다', () => {
  assert.deepEqual(parsePageRange('1-3, 5', 10).indices, [0, 1, 2, 4]);
  assert.deepEqual(parsePageRange('8-', 10).indices, [7, 8, 9]);
  assert.deepEqual(parsePageRange('-2', 10).indices, [0, 1]);
  assert.deepEqual(parsePageRange('3,3,1-3', 10).indices, [2, 0, 1]);
  assert.deepEqual(parsePageRange('2 4', 10).indices, [1, 3]);
});

test('잘못된 범위는 이유와 함께 거절한다', () => {
  assert.match(parsePageRange('', 10).error, /입력/);
  assert.match(parsePageRange('0', 10).error, /1 ~ 10/);
  assert.match(parsePageRange('11', 10).error, /1 ~ 10/);
  assert.match(parsePageRange('5-2', 10).error, /시작이 끝보다/);
  assert.match(parsePageRange('abc', 10).error, /올바른 범위/);
  assert.match(parsePageRange('1', 0).error, /쪽이 없습니다/);
});

test('옵션은 허용 범위로 정리된다', () => {
  const o = normalizePrintOptions({ copies: 500, perSheet: 3, paper: 'XX', scalePercent: 1, duplex: 'bad', marginMm: -4 });
  assert.equal(o.copies, 99);
  assert.equal(o.perSheet, 1);
  assert.equal(o.paper, 'auto');
  assert.equal(o.scalePercent, 10);
  assert.equal(o.duplex, 'simplex');
  assert.equal(o.marginMm, 0);
  assert.equal(normalizePrintOptions(null).orientation, 'auto');
});

test('용지는 쪽 크기에 가장 가까운 규격으로 고른다', () => {
  assert.equal(nearestPaperId(A4), 'A4');
  assert.equal(nearestPaperId(A4_LAND), 'A4');
  assert.equal(nearestPaperId([612, 792]), 'Letter');
  assert.equal(nearestPaperId([419.5, 595.3]), 'A5');
  assert.equal(nearestPaperId([841.9, 1190.6]), 'A3');
});

test('A4 쪽을 A4 용지에 맞춤 인쇄하면 여백 안에 가운데 놓인다', () => {
  const layout = layoutSheets([A4], { margin: 'none' });
  assert.equal(layout.paperId, 'A4');
  assert.equal(layout.landscape, false);
  assert.deepEqual(layout.sheetMm, [210, 297]);
  const cell = layout.sheets[0].cells[0];
  assert.ok(Math.abs(cell.img.w - 210) < 0.1 && Math.abs(cell.img.h - 297) < 0.1);
  assert.equal(cell.img.x, 0);

  const margined = layoutSheets([A4], { margin: 'default' });
  const m = margined.sheets[0].cells[0];
  assert.equal(margined.marginMm, 5);
  assert.ok(m.img.w <= 200.01 && m.img.w > 195, String(m.img.w));
  // 위치는 칸 안에서 가운데
  assert.ok(Math.abs(m.img.x + m.img.w / 2 - m.cell.w / 2) < 0.02);
});

test('가로 쪽은 자동으로 가로 용지가 된다', () => {
  const layout = layoutSheets([A4_LAND], {});
  assert.equal(layout.landscape, true);
  assert.deepEqual(layout.sheetMm, [297, 210]);
  assert.equal(layout.electron.landscape, true);
  assert.equal(layout.electron.pageSize, 'A4');
});

test('가로·세로가 섞인 문서: 자동 방향이면 어긋난 쪽을 돌려 용지를 채운다', () => {
  const layout = layoutSheets([A4, A4_LAND], { margin: 'none' });
  assert.equal(layout.landscape, false); // 첫 쪽 기준
  const [portrait, land] = layout.sheets.map((s) => s.cells[0]);
  assert.equal(portrait.rotated, false);
  assert.equal(land.rotated, true);
  // 돌리기 전 상자는 쪽 비율(가로로 긴 상자), 돌린 뒤 용지 세로 297mm 를 채운다
  assert.ok(land.img.w > land.img.h);
  assert.ok(Math.abs(land.img.w - 297) < 0.2, String(land.img.w));
  // 가운데 기준이라 돌려도 칸 가운데에 온다
  assert.ok(Math.abs(land.img.x + land.img.w / 2 - land.cell.w / 2) < 0.02);
  assert.ok(Math.abs(land.img.y + land.img.h / 2 - land.cell.h / 2) < 0.02);
  const html = buildPrintHtml(layout, ['file:///a.png', 'file:///b.png']);
  assert.equal((html.match(/rotate\(90deg\)/g) ?? []).length, 1);

  // 방향을 직접 정했거나 여러 쪽을 모으면 돌리지 않는다
  assert.equal(layoutSheets([A4, A4_LAND], { orientation: 'portrait' }).sheets[1].cells[0].rotated, false);
  assert.equal(layoutSheets([A4, A4_LAND], { perSheet: 2 }).sheets[0].cells[1].rotated, false);
});

test('방향을 직접 고르면 그대로 따른다', () => {
  assert.equal(layoutSheets([A4], { orientation: 'landscape' }).landscape, true);
  assert.equal(layoutSheets([A4_LAND], { orientation: 'portrait' }).landscape, false);
});

test('크기 방식: 실제 크기, 큰 쪽만 축소, 사용자 지정', () => {
  const actual = layoutSheets([A4], { scale: 'actual', margin: 'none', paper: 'A5' });
  assert.equal(actual.sheets[0].cells[0].scale, 1);
  assert.ok(actual.sheets[0].cells[0].img.x < 0, '칸보다 크면 음수 좌표로 가운데에서 잘린다');

  const shrinkBig = layoutSheets([A4], { scale: 'shrink', margin: 'none', paper: 'A5' });
  assert.ok(shrinkBig.sheets[0].cells[0].scale < 0.75);
  const shrinkSmall = layoutSheets([[283.5, 396.9]], { scale: 'shrink', margin: 'none', paper: 'A4' });
  assert.equal(shrinkSmall.sheets[0].cells[0].scale, 1);

  const custom = layoutSheets([A4], { scale: 'custom', scalePercent: 50, margin: 'none' });
  assert.equal(custom.sheets[0].cells[0].scale, 0.5);
});

test('한 장에 여러 쪽: 2·4·6·9', () => {
  const pages = Array.from({ length: 5 }, () => A4);
  const two = layoutSheets(pages, { perSheet: 2 });
  assert.equal(two.landscape, true); // 세로 쪽 2개는 가로 용지에
  assert.equal(two.sheets.length, 3);
  assert.equal(two.sheets[0].cells.length, 2);
  assert.equal(two.sheets[2].cells.length, 1);
  assert.ok(two.sheets[0].cells[1].cell.x > two.sheets[0].cells[0].cell.x);

  const four = layoutSheets(pages, { perSheet: 4 });
  assert.equal(four.sheets.length, 2);
  assert.equal(four.sheets[0].cells[2].cell.y, four.sheets[0].cells[3].cell.y);
  assert.ok(four.sheets[0].cells[2].cell.y > four.sheets[0].cells[0].cell.y);

  const nine = layoutSheets(Array.from({ length: 9 }, () => A4), { perSheet: 9, margin: 'none' });
  assert.equal(nine.sheets.length, 1);
  assert.equal(nine.sheets[0].cells.length, 9);
  // 칸이 서로 겹치지 않는다
  const cells = nine.sheets[0].cells.map((c) => c.cell);
  for (let a = 0; a < cells.length; a += 1) {
    for (let b = a + 1; b < cells.length; b += 1) {
      const x = cells[a].x < cells[b].x + cells[b].w && cells[b].x < cells[a].x + cells[a].w;
      const y = cells[a].y < cells[b].y + cells[b].h && cells[b].y < cells[a].y + cells[a].h;
      assert.equal(x && y, false);
    }
  }
});

test('B5 는 이름이 아니라 마이크론 크기로 넘긴다', () => {
  const layout = layoutSheets([A4], { paper: 'B5' });
  assert.deepEqual(layout.electron.pageSize, { width: 176000, height: 250000 });
});

test('해상도·배율 계산', () => {
  assert.equal(dpiForSheets(1), 300);
  assert.equal(dpiForSheets(100), 200);
  assert.equal(dpiForSheets(400), 150);
  const layout = layoutSheets([A4], { margin: 'none' });
  const zoom = renderZoomFor(layout.sheets[0].cells[0], A4, 300);
  // A4 한 장 300dpi = 72dpi 대비 약 4.17배
  assert.ok(zoom > 4.1 && zoom < 4.2, String(zoom));
});

test('인쇄 HTML 은 장마다 용지 크기 블록과 그림을 담고 흑백이면 grayscale 을 건다', () => {
  const layout = layoutSheets([A4, A4], { margin: 'none' });
  const html = buildPrintHtml(layout, ['file:///a.png', 'file:///b "x".png']);
  assert.match(html, /@page\{size:210mm 297mm;margin:0\}/);
  assert.equal((html.match(/class="sheet"/g) ?? []).length, 2);
  assert.match(html, /src="file:\/\/\/a\.png"/);
  assert.match(html, /%22x%22/);
  assert.doesNotMatch(html, /grayscale/);
  const gray = buildPrintHtml(layoutSheets([A4], { color: false }), ['file:///a.png']);
  assert.match(gray, /grayscale\(1\)/);
});
