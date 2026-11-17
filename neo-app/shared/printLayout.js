/**
 * 인쇄 배치 계산 (렌더러의 인쇄 미리보기와 Electron 의 실제 인쇄가 같은 함수를 쓴다).
 *
 * 인쇄 방식: 쪽을 그림으로 그린 HTML 을 Chromium 이 프린터로 보낸다. 미리보기와 인쇄물이
 * 같은 배치 결과(layoutSheets)에서 나오므로, 미리보기에 보이는 대로 인쇄된다.
 *
 * 단위: 용지·여백·배치는 mm, 문서 쪽 크기는 pt(1/72 inch).
 */

const MM_PER_PT = 25.4 / 72;

/** 용지 규격. electron 은 webContents.print 의 pageSize 이름 (없으면 마이크론 크기로 넘긴다). */
export const PAPER_SIZES = [
  { id: 'A3', label: 'A3 (297 × 420 mm)', mm: [297, 420], electron: 'A3' },
  { id: 'A4', label: 'A4 (210 × 297 mm)', mm: [210, 297], electron: 'A4' },
  { id: 'A5', label: 'A5 (148 × 210 mm)', mm: [148, 210], electron: 'A5' },
  { id: 'B5', label: 'B5 (176 × 250 mm)', mm: [176, 250], electron: null },
  { id: 'Letter', label: 'Letter (8.5 × 11 in)', mm: [215.9, 279.4], electron: 'Letter' },
  { id: 'Legal', label: 'Legal (8.5 × 14 in)', mm: [215.9, 355.6], electron: 'Legal' },
  { id: 'Tabloid', label: 'Tabloid (11 × 17 in)', mm: [279.4, 431.8], electron: 'Tabloid' },
];

export const PER_SHEET_CHOICES = [1, 2, 4, 6, 9];
export const MARGIN_PRESETS = { none: 0, default: 5 };
export const COPIES_MAX = 99;
export const SCALE_PERCENT_MIN = 10;
export const SCALE_PERCENT_MAX = 400;
/** 여러 쪽을 한 장에 모을 때 칸 사이 간격 (mm). */
const CELL_GAP_MM = 3;

/** @typedef {{
 *   printer: string, copies: number, collate: boolean, color: boolean,
 *   duplex: 'simplex' | 'longEdge' | 'shortEdge',
 *   paper: string, orientation: 'auto' | 'portrait' | 'landscape',
 *   scale: 'fit' | 'shrink' | 'actual' | 'custom', scalePercent: number,
 *   margin: 'none' | 'default' | 'custom', marginMm: number,
 *   perSheet: number, systemDialog: boolean,
 * }} PrintOptions */

/** @type {PrintOptions} */
export const DEFAULT_PRINT_OPTIONS = {
  printer: '',
  copies: 1,
  collate: true,
  color: true,
  duplex: 'simplex',
  paper: 'auto',
  orientation: 'auto',
  scale: 'fit',
  scalePercent: 100,
  margin: 'default',
  marginMm: 10,
  perSheet: 1,
  systemDialog: false,
};

function clampNumber(value, min, max, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function pick(value, allowed, fallback) {
  return allowed.includes(value) ? value : fallback;
}

/** 저장돼 있던 값·사용자 입력을 허용 범위로 정리한다. */
export function normalizePrintOptions(raw) {
  const src = raw && typeof raw === 'object' ? raw : {};
  const base = DEFAULT_PRINT_OPTIONS;
  return {
    printer: typeof src.printer === 'string' ? src.printer : base.printer,
    copies: Math.round(clampNumber(src.copies, 1, COPIES_MAX, base.copies)),
    collate: src.collate === undefined ? base.collate : Boolean(src.collate),
    color: src.color === undefined ? base.color : Boolean(src.color),
    duplex: pick(src.duplex, ['simplex', 'longEdge', 'shortEdge'], base.duplex),
    paper: pick(src.paper, ['auto', ...PAPER_SIZES.map((p) => p.id)], base.paper),
    orientation: pick(src.orientation, ['auto', 'portrait', 'landscape'], base.orientation),
    scale: pick(src.scale, ['fit', 'shrink', 'actual', 'custom'], base.scale),
    scalePercent: Math.round(clampNumber(src.scalePercent, SCALE_PERCENT_MIN, SCALE_PERCENT_MAX, base.scalePercent)),
    margin: pick(src.margin, ['none', 'default', 'custom'], base.margin),
    marginMm: Math.round(clampNumber(src.marginMm, 0, 50, base.marginMm) * 10) / 10,
    perSheet: PER_SHEET_CHOICES.includes(Number(src.perSheet)) ? Number(src.perSheet) : base.perSheet,
    systemDialog: Boolean(src.systemDialog),
  };
}

export function marginMmOf(options) {
  if (options.margin === 'custom') return options.marginMm;
  return MARGIN_PRESETS[options.margin] ?? MARGIN_PRESETS.default;
}

/**
 * "1-3, 5, 8-" 같은 범위 글을 0 기반 쪽 번호 배열로 바꾼다. 중복은 한 번만, 입력한 순서를 지킨다.
 * @returns {{ indices: number[], error: string }}
 */
export function parsePageRange(text, pageCount) {
  const source = String(text ?? '').trim();
  if (!source) return { indices: [], error: '인쇄할 쪽을 입력해 주세요. 예: 1-3, 5' };
  if (!(pageCount > 0)) return { indices: [], error: '문서에 쪽이 없습니다.' };
  const seen = new Set();
  const indices = [];
  for (const rawPart of source.split(/[,\s]+/)) {
    const part = rawPart.trim();
    if (!part) continue;
    const match = /^(\d*)\s*-\s*(\d*)$/.exec(part);
    let from;
    let to;
    if (match && (match[1] || match[2])) {
      from = match[1] ? Number(match[1]) : 1;
      to = match[2] ? Number(match[2]) : pageCount;
    } else if (/^\d+$/.test(part)) {
      from = Number(part);
      to = from;
    } else {
      return { indices: [], error: `"${part}" 은(는) 올바른 범위가 아닙니다. 예: 1-3, 5` };
    }
    if (from < 1 || to < 1 || from > pageCount || to > pageCount) {
      return { indices: [], error: `쪽 번호는 1 ~ ${pageCount} 사이여야 합니다.` };
    }
    if (from > to) return { indices: [], error: `"${part}" 은(는) 시작이 끝보다 큽니다.` };
    for (let page = from; page <= to; page += 1) {
      if (!seen.has(page)) {
        seen.add(page);
        indices.push(page - 1);
      }
    }
  }
  if (!indices.length) return { indices: [], error: '인쇄할 쪽을 입력해 주세요. 예: 1-3, 5' };
  return { indices, error: '' };
}

/** 쪽 크기에 가장 가까운 규격 (면적이 아니라 긴 변·짧은 변 차이로 비교). */
export function nearestPaperId(pagePt) {
  const [w, h] = pagePt ?? [595, 842];
  const short = Math.min(w, h) * MM_PER_PT;
  const long = Math.max(w, h) * MM_PER_PT;
  let best = 'A4';
  let bestDiff = Infinity;
  for (const paper of PAPER_SIZES) {
    if (!['A3', 'A4', 'A5', 'Letter', 'Legal'].includes(paper.id)) continue;
    const diff = Math.abs(paper.mm[0] - short) + Math.abs(paper.mm[1] - long);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = paper.id;
    }
  }
  return best;
}

function gridFor(perSheet, landscape) {
  switch (perSheet) {
    case 2:
      return landscape ? { cols: 2, rows: 1 } : { cols: 1, rows: 2 };
    case 4:
      return { cols: 2, rows: 2 };
    case 6:
      return landscape ? { cols: 3, rows: 2 } : { cols: 2, rows: 3 };
    case 9:
      return { cols: 3, rows: 3 };
    default:
      return { cols: 1, rows: 1 };
  }
}

const round2 = (v) => Math.round(v * 100) / 100;

/**
 * @param {number[][]} pagesPt 인쇄할 쪽의 [너비, 높이] (pt), 인쇄 순서대로
 * @param {Partial<PrintOptions>} rawOptions
 */
export function layoutSheets(pagesPt, rawOptions) {
  const options = normalizePrintOptions(rawOptions);
  const pages = Array.isArray(pagesPt) ? pagesPt : [];
  const first = pages[0] ?? [595, 842];
  const paperId = options.paper === 'auto' ? nearestPaperId(first) : options.paper;
  const paper = PAPER_SIZES.find((p) => p.id === paperId) ?? PAPER_SIZES[1];
  const [portraitW, portraitH] = paper.mm;

  const pageLandscape = first[0] > first[1];
  let landscape;
  if (options.orientation === 'landscape') landscape = true;
  else if (options.orientation === 'portrait') landscape = false;
  else if (options.perSheet === 2 || options.perSheet === 6) landscape = !pageLandscape;
  else landscape = pageLandscape;

  const sheetW = landscape ? portraitH : portraitW;
  const sheetH = landscape ? portraitW : portraitH;
  const margin = Math.min(marginMmOf(options), Math.min(sheetW, sheetH) / 2 - 1);
  const { cols, rows } = gridFor(options.perSheet, landscape);
  const gap = options.perSheet > 1 ? CELL_GAP_MM : 0;
  const areaW = sheetW - margin * 2;
  const areaH = sheetH - margin * 2;
  const cellW = (areaW - gap * (cols - 1)) / cols;
  const cellH = (areaH - gap * (rows - 1)) / rows;

  const sheets = [];
  for (let start = 0; start < pages.length; start += options.perSheet) {
    const cells = [];
    for (let slot = 0; slot < options.perSheet; slot += 1) {
      const i = start + slot;
      if (i >= pages.length) break;
      const col = slot % cols;
      const row = Math.floor(slot / cols);
      const cellX = margin + col * (cellW + gap);
      const cellY = margin + row * (cellH + gap);
      const pageWmm = pages[i][0] * MM_PER_PT;
      const pageHmm = pages[i][1] * MM_PER_PT;
      // 방향이 '자동'이고 한 장에 한 쪽씩이면, 용지 방향과 어긋난 쪽은 90도 돌려 용지를 채운다.
      // (인쇄 작업은 방향이 하나뿐이라 가로·세로가 섞인 문서는 이렇게 맞춘다.)
      const rotated = options.perSheet === 1 && options.orientation === 'auto' && pageWmm > pageHmm !== landscape;
      const fitScale = rotated
        ? Math.min(cellW / pageHmm, cellH / pageWmm)
        : Math.min(cellW / pageWmm, cellH / pageHmm);
      let scale;
      if (options.perSheet > 1) scale = fitScale;
      else if (options.scale === 'fit') scale = fitScale;
      else if (options.scale === 'shrink') scale = Math.min(1, fitScale);
      else if (options.scale === 'actual') scale = 1;
      else scale = options.scalePercent / 100;
      const imgW = pageWmm * scale;
      const imgH = pageHmm * scale;
      cells.push({
        i,
        cell: { x: round2(cellX), y: round2(cellY), w: round2(cellW), h: round2(cellH) },
        rotated,
        // 칸 안에서의 위치(돌리기 전 상자, 가운데 기준). 칸보다 크면 음수가 되고 칸 밖은 잘린다.
        img: {
          x: round2((cellW - imgW) / 2),
          y: round2((cellH - imgH) / 2),
          w: round2(imgW),
          h: round2(imgH),
        },
        scale: Math.round(scale * 1000) / 1000,
      });
    }
    sheets.push({ cells });
  }

  return {
    options,
    paperId,
    landscape,
    sheetMm: [round2(sheetW), round2(sheetH)],
    marginMm: round2(margin),
    sheets,
    // webContents.print 에 그대로 넘기는 용지 값 (세로 기준 크기 + landscape 플래그)
    electron: {
      pageSize: paper.electron ?? { width: Math.round(portraitW * 1000), height: Math.round(portraitH * 1000) },
      landscape,
    },
  };
}

/** 렌더링할 해상도(dpi)에서 한 쪽을 그릴 때의 확대 배율. */
export function renderZoomFor(cellInfo, pagePt, dpi) {
  const pixelsWide = (cellInfo.img.w / 25.4) * dpi;
  return Math.max(0.1, pixelsWide / pagePt[0]);
}

/** 인쇄 장수에 따라 해상도를 정한다 (장수가 많으면 메모리·스풀 크기를 줄인다). */
export function dpiForSheets(sheetCount) {
  if (sheetCount <= 40) return 300;
  if (sheetCount <= 150) return 200;
  return 150;
}

/**
 * 인쇄용 HTML. 쪽 그림은 imageUrls[i] (layout.sheets[*].cells[*].i 와 같은 인덱스).
 * @param {ReturnType<typeof layoutSheets>} layout
 * @param {string[]} imageUrls
 */
export function buildPrintHtml(layout, imageUrls) {
  const [w, h] = layout.sheetMm;
  const gray = layout.options.color ? '' : 'filter:grayscale(1);';
  const body = layout.sheets
    .map((sheet) => {
      const cells = sheet.cells
        .map(
          (c) =>
            `<div class="cell" style="left:${c.cell.x}mm;top:${c.cell.y}mm;width:${c.cell.w}mm;height:${c.cell.h}mm">` +
            `<img src="${String(imageUrls[c.i]).replace(/"/g, '%22')}" style="left:${c.img.x}mm;top:${c.img.y}mm;width:${c.img.w}mm;height:${c.img.h}mm${c.rotated ? ';transform:rotate(90deg)' : ''}" alt=""></div>`,
        )
        .join('');
      return `<div class="sheet">${cells}</div>`;
    })
    .join('\n');
  return (
    '<!doctype html><html><head><meta charset="utf-8"><title>Tiny PDF Editor print</title><style>' +
    `@page{size:${w}mm ${h}mm;margin:0}` +
    'html,body{margin:0;padding:0;background:#fff}' +
    `.sheet{position:relative;width:${w}mm;height:${h}mm;overflow:hidden;break-after:page;page-break-after:always}` +
    '.sheet:last-child{break-after:auto;page-break-after:auto}' +
    '.cell{position:absolute;overflow:hidden}' +
    `.cell img{position:absolute;display:block;${gray}}` +
    `</style></head><body>${body}</body></html>`
  );
}
