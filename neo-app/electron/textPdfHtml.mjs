/**
 * TXT / Markdown / JSON / HTML → printable HTML (NAS4USB-style). No Electron dependency.
 */
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const TEXT_EXTENSIONS = new Set(['.txt', '.md', '.markdown', '.json']);
const HTML_EXTENSIONS = new Set(['.html', '.htm']);

const PRINT_PAGINATION_CSS = `
@media print {
  h1, h2, h3, h4, h5, h6 {
    break-after: avoid;
    page-break-after: avoid;
    break-inside: avoid;
    page-break-inside: avoid;
  }
  p, li, dd, dt { orphans: 3; widows: 3; }
  img, svg, figure {
    break-inside: avoid;
    page-break-inside: avoid;
    max-width: 100% !important;
    max-height: 360mm;
    height: auto;
    object-fit: contain;
  }
  pre, blockquote {
    break-inside: avoid;
    page-break-inside: avoid;
  }
  thead { display: table-header-group; }
  tfoot { display: table-footer-group; }
  tr, th, td {
    break-inside: avoid;
    page-break-inside: avoid;
  }
}
`;

const MARKDOWN_EXPORT_CSS = `
  @page { size: A4; margin: 12mm; }
  html, body { margin: 0; padding: 0; background: #fff; }
  body {
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
    color: #1e293b;
    line-height: 1.6;
  }
  .markdown-export {
    box-sizing: border-box;
    width: 100%;
    margin: 0 auto;
  }
  .markdown-export h1 { font-size: 1.75rem; font-weight: 700; margin: 1.25em 0 0.5em; }
  .markdown-export h2 { font-size: 1.4rem; font-weight: 700; margin: 1.1em 0 0.45em; }
  .markdown-export h3 { font-size: 1.2rem; font-weight: 600; margin: 1em 0 0.4em; }
  .markdown-export h4, .markdown-export h5, .markdown-export h6 {
    font-size: 1.05rem; font-weight: 600; margin: 0.9em 0 0.35em;
  }
  .markdown-export p { margin: 0.55em 0; }
  .markdown-export ul, .markdown-export ol { margin: 0.55em 0; padding-left: 1.5em; }
  .markdown-export ol { list-style: decimal; }
  .markdown-export ul { list-style: disc; }
  .markdown-export blockquote {
    margin: 0.75em 0;
    padding: 0.25em 0 0.25em 0.9em;
    border-left: 3px solid #cbd5e1;
    color: #475569;
  }
  .markdown-export code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.9em;
    background: #f1f5f9;
    padding: 0.1em 0.35em;
    border-radius: 3px;
  }
  .markdown-export pre {
    background: #0f172a;
    color: #e2e8f0;
    padding: 12px 14px;
    border-radius: 6px;
    overflow: auto;
  }
  .markdown-export pre code { background: transparent; padding: 0; color: inherit; }
  .markdown-export a { color: #0369a1; }
  .markdown-export hr { border: 0; border-top: 1px solid #cbd5e1; margin: 1.25em 0; }
  .markdown-export img { max-width: 100%; height: auto; margin: 0.75em 0; }
  .markdown-export table { border-collapse: collapse; width: 100%; margin: 0.75em 0; }
  .markdown-export th, .markdown-export td {
    border: 1px solid #cbd5e1;
    padding: 0.4em 0.6em;
    vertical-align: top;
  }
  .markdown-export th { font-weight: 600; background: #f8fafc; }
  /* TXT / JSON: 본문과 같은 밝은 배경 (MD 코드블록 pre 스타일을 덮어쓴다). */
  .markdown-export pre.plain-text {
    white-space: pre-wrap;
    word-break: break-word;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.92em;
    margin: 0;
    padding: 0;
    background: transparent;
    color: #1e293b;
    border-radius: 0;
    overflow: visible;
  }
  @media print {
    .markdown-export { max-width: none; }
  }
  ${PRINT_PAGINATION_CSS}
`;

/**
 * @param {string} filePath
 */
export function isHtmlPath(filePath) {
  return HTML_EXTENSIONS.has(path.extname(String(filePath || '')).toLowerCase());
}

/**
 * TXT / MD / JSON / HTML — Chromium PDF 변환 대상.
 * @param {string} filePath
 */
export function isTextPath(filePath) {
  const ext = path.extname(String(filePath || '')).toLowerCase();
  return TEXT_EXTENSIONS.has(ext) || HTML_EXTENSIONS.has(ext);
}

/**
 * 유효한 JSON 이면 들여쓰기, 아니면 원문 그대로.
 * @param {string} text
 */
export function formatJsonText(text) {
  try {
    return JSON.stringify(JSON.parse(String(text ?? '')), null, 2);
  } catch {
    return String(text ?? '');
  }
}

/**
 * @param {string} value
 */
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"]/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch],
  );
}

/**
 * @param {string} line
 */
function renderInlineMarkdown(line) {
  let html = escapeHtml(line);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/_([^_]+)_/g, '<em>$1</em>');
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return html;
}

/**
 * CommonMark-style subset (ported from NAS4USB markdown.js).
 * @param {string} source
 */
export function renderMarkdown(source) {
  const lines = String(source ?? '')
    .replace(/\r\n/g, '\n')
    .split('\n');
  /** @type {string[]} */
  const blocks = [];
  /** @type {string[]} */
  const listItems = [];
  /** @type {string[]} */
  const codeLines = [];
  let inCodeBlock = false;
  /** @type {'ul' | 'ol' | null} */
  let listKind = null;

  const flushList = () => {
    if (listItems.length === 0) return;
    const tag = listKind === 'ol' ? 'ol' : 'ul';
    blocks.push(
      `<${tag}>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('')}</${tag}>`,
    );
    listItems.length = 0;
    listKind = null;
  };

  for (const rawLine of lines) {
    const line = rawLine ?? '';

    if (line.startsWith('```')) {
      flushList();
      if (!inCodeBlock) {
        inCodeBlock = true;
        codeLines.length = 0;
      } else {
        inCodeBlock = false;
        blocks.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    if (!line.trim()) {
      flushList();
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      flushList();
      blocks.push('<hr />');
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushList();
      const level = heading[1].length;
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushList();
      blocks.push(`<blockquote><p>${renderInlineMarkdown(quote[1])}</p></blockquote>`);
      continue;
    }

    const listItem = line.match(/^[-*+]\s+(.+)$/);
    if (listItem) {
      if (listKind && listKind !== 'ul') flushList();
      listKind = 'ul';
      listItems.push(listItem[1]);
      continue;
    }

    const orderedItem = line.match(/^\d+\.\s+(.+)$/);
    if (orderedItem) {
      if (listKind && listKind !== 'ol') flushList();
      listKind = 'ol';
      listItems.push(orderedItem[1]);
      continue;
    }

    flushList();
    blocks.push(`<p>${renderInlineMarkdown(line)}</p>`);
  }

  flushList();
  if (inCodeBlock && codeLines.length > 0) {
    blocks.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
  }
  return blocks.join('\n') || '<p></p>';
}

/**
 * @param {string} text
 */
function plainTextToBodyHtml(text) {
  return `<pre class="plain-text">${escapeHtml(String(text ?? ''))}</pre>`;
}

/**
 * @param {string} bodyHtml
 * @param {string} title
 */
export function buildStandaloneHtml(bodyHtml, title) {
  const safeTitle = escapeHtml(title || 'document');
  return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${safeTitle}</title>
<style>
${MARKDOWN_EXPORT_CSS}
</style>
</head>
<body>
<div class="markdown-export">${bodyHtml}</div>
</body>
</html>
`;
}

/**
 * @param {string} sourcePath
 * @param {string} text
 */
export function textFileToHtml(sourcePath, text) {
  const ext = path.extname(sourcePath).toLowerCase();
  const title = path.basename(sourcePath, path.extname(sourcePath)) || 'document';
  if (HTML_EXTENSIONS.has(ext)) {
    return htmlSourceToPrintableHtml(sourcePath, text, title);
  }
  let body;
  if (ext === '.md' || ext === '.markdown') {
    body = renderMarkdown(text);
  } else if (ext === '.json') {
    body = plainTextToBodyHtml(formatJsonText(text));
  } else {
    body = plainTextToBodyHtml(text);
  }
  return buildStandaloneHtml(body, title);
}

/**
 * 기존 HTML 문서/조각을 인쇄용으로 맞춘다. 상대 경로 자원은 base href 로 유지한다.
 * @param {string} sourcePath
 * @param {string} rawHtml
 * @param {string} [title]
 */
export function htmlSourceToPrintableHtml(sourcePath, rawHtml, title) {
  const docTitle = title || path.basename(sourcePath, path.extname(sourcePath)) || 'document';
  const safeTitle = escapeHtml(docTitle);
  const baseHref = pathToFileURL(`${path.resolve(path.dirname(sourcePath))}${path.sep}`).href;
  const inject = `<base href="${escapeHtml(baseHref)}"><style>
@page { size: A4; margin: 12mm; }
${PRINT_PAGINATION_CSS}
</style>`;
  const text = String(rawHtml ?? '');
  if (/<!DOCTYPE/i.test(text) || /<html[\s>]/i.test(text)) {
    if (/<\/head>/i.test(text)) {
      return text.replace(/<\/head>/i, `${inject}</head>`);
    }
    if (/<body[\s>]/i.test(text)) {
      return text.replace(/<body/i, `<head>${inject}<title>${safeTitle}</title></head><body`);
    }
    return `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8" />${inject}<title>${safeTitle}</title></head><body>${text}</body></html>`;
  }
  // 조각 HTML: 마크다운 내보내기와 같은 껍데기에 넣고, base 는 head 에 추가.
  const wrapped = buildStandaloneHtml(text, docTitle);
  return wrapped.replace(/<\/head>/i, `${inject}</head>`);
}
