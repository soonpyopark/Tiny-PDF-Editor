/**
 * TXT / Markdown → PDF via Chromium printToPDF (NAS4USB-quality layout).
 */
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { BrowserWindow } from 'electron';
import {
  isHtmlPath,
  isTextPath,
  textFileToHtml,
} from './textPdfHtml.mjs';

export {
  buildStandaloneHtml,
  isHtmlPath,
  isTextPath,
  renderMarkdown,
  textFileToHtml,
} from './textPdfHtml.mjs';

const MM_PER_INCH = 25.4;
const LOAD_TIMEOUT_MS = 30_000;
const SETTLE_MS = 250;

/**
 * @param {Buffer} raw
 */
function decodeTextBuffer(raw) {
  for (const encoding of ['utf-8', 'utf16le', 'latin1']) {
    try {
      if (encoding === 'utf-8') {
        return raw.toString('utf8').replace(/^\uFEFF/, '');
      }
      return raw.toString(/** @type {BufferEncoding} */ (encoding));
    } catch {
      /* try next */
    }
  }
  return raw.toString('utf8');
}

/**
 * @param {string} filePath
 */
export async function readTextFile(filePath) {
  const raw = await fs.readFile(filePath);
  if (raw.length >= 3 && raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf) {
    return raw.subarray(3).toString('utf8');
  }
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(raw);
  } catch {
    try {
      return new TextDecoder('euc-kr').decode(raw);
    } catch {
      return decodeTextBuffer(raw);
    }
  }
}

/**
 * @param {Promise<unknown>} promise
 * @param {number} timeoutMs
 * @param {string} message
 */
async function withTimeout(promise, timeoutMs, message) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(message)), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * @param {{
 *   html: string,
 *   fileName?: string,
 *   pageSize?: string,
 *   landscape?: boolean,
 *   marginMm?: number,
 *   printBackground?: boolean,
 *   preferCssPageSize?: boolean,
 * }} input
 * @returns {Promise<Buffer>}
 */
export async function convertHtmlToPdfBuffer(input) {
  const html = String(input?.html ?? '');
  if (!html.trim()) throw new Error('PDF로 내보낼 내용이 없습니다.');

  const marginInches = Math.max(0, Number(input?.marginMm ?? 12)) / MM_PER_INCH;
  const workDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tiny-neo-text-pdf-'));
  const htmlPath = path.join(workDir, 'document.html');
  await fs.writeFile(htmlPath, html, 'utf8');

  const win = new BrowserWindow({
    show: false,
    width: 1240,
    height: 1754,
    webPreferences: {
      javascript: false,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  try {
    await withTimeout(
      win.loadFile(htmlPath),
      LOAD_TIMEOUT_MS,
      '텍스트 PDF로 변환하는 데 시간이 너무 오래 걸립니다.',
    );
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));

    const pdf = await win.webContents.printToPDF({
      pageSize: /** @type {'A4'} */ (input?.pageSize || 'A4'),
      landscape: Boolean(input?.landscape),
      printBackground: input?.printBackground !== false,
      margins: {
        top: marginInches,
        bottom: marginInches,
        left: marginInches,
        right: marginInches,
      },
      preferCSSPageSize: input?.preferCssPageSize !== false,
    });
    return Buffer.from(pdf);
  } finally {
    if (!win.isDestroyed()) win.destroy();
    await fs.rm(workDir, { recursive: true, force: true }).catch(() => {});
  }
}

/**
 * Convert a .txt / .md / .markdown / .html / .htm file to a PDF on disk.
 * @param {string} sourcePath
 * @param {string} outputPath
 * @returns {Promise<string>} absolute output path
 */
export async function convertTextFileToPdf(sourcePath, outputPath) {
  const source = path.resolve(String(sourcePath || ''));
  if (!isTextPath(source)) {
    throw new Error('TXT, Markdown, JSON 또는 HTML 파일만 변환할 수 있습니다.');
  }
  const text = await readTextFile(source);
  const html = textFileToHtml(source, text);
  const pdf = await convertHtmlToPdfBuffer({
    html,
    fileName: path.basename(source),
    pageSize: 'A4',
    // HTML 원본은 @page / 자체 여백을 존중하고, TXT·MD 는 12mm 여백.
    marginMm: isHtmlPath(source) ? 0 : 12,
    preferCssPageSize: true,
  });
  const out = path.resolve(String(outputPath || ''));
  await fs.mkdir(path.dirname(out), { recursive: true });
  await fs.writeFile(out, pdf);
  return out;
}
