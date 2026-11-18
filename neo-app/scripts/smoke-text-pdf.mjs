/**
 * One-shot Chromium TXT/MD/HTML → PDF smoke
 * (run via: node node_modules/electron/cli.js scripts/smoke-text-pdf.mjs).
 */
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { app } from 'electron';

const keepDirEarly = path.resolve('.cache/smoke-text-pdf');
fs.mkdirSync(keepDirEarly, { recursive: true });
fs.writeFileSync(path.join(keepDirEarly, 'started.txt'), `start ${new Date().toISOString()}\n`);

const { convertTextFileToPdf } = await import('../electron/textPdfExport.mjs');

// Headless convert: do not quit when temporary BrowserWindows close.
app.on('window-all-closed', (event) => {
  event.preventDefault?.();
});

async function main() {
  app.setPath('userData', path.join(os.tmpdir(), 'tiny-neo-smoke-userdata'));
  await app.whenReady();
  fs.writeFileSync(path.join(keepDirEarly, 'ready.txt'), 'ready\n');
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'tiny-neo-smoke-text-'));
  const keepDir = path.resolve('.cache/smoke-text-pdf');
  await fsp.mkdir(keepDir, { recursive: true });

  const md = path.join(dir, 'sample.md');
  await fsp.writeFile(
    md,
    '# 제목\n\n일반 문단과 **굵게**, `코드`.\n\n- 항목 하나\n- 항목 둘\n\n> 인용문\n\n```\ncode block\n```\n',
    'utf8',
  );
  const html = path.join(dir, 'sample.html');
  await fsp.writeFile(
    html,
    '<!DOCTYPE html><html><head><meta charset="utf-8"><title>HTML</title></head><body><h1>HTML 제목</h1><p>본문 <strong>강조</strong></p></body></html>',
    'utf8',
  );

  const mdOut = path.join(keepDir, 'sample-md.pdf');
  const htmlOut = path.join(keepDir, 'sample-html.pdf');
  await convertTextFileToPdf(md, mdOut);
  await convertTextFileToPdf(html, htmlOut);
  const mdStat = await fsp.stat(mdOut);
  const htmlStat = await fsp.stat(htmlOut);
  if (mdStat.size < 500 || htmlStat.size < 500) {
    throw new Error(`PDF too small: md=${mdStat.size} html=${htmlStat.size}`);
  }
  const report = `OK md=${mdStat.size} html=${htmlStat.size}\n`;
  await fsp.writeFile(path.join(keepDir, 'ok.txt'), report, 'utf8');
  process.stdout.write(report);
  app.exit(0);
}

main().catch(async (err) => {
  const message = err instanceof Error ? err.stack || err.message : String(err);
  try {
    const keepDir = path.resolve('.cache/smoke-text-pdf');
    fs.mkdirSync(keepDir, { recursive: true });
    fs.writeFileSync(path.join(keepDir, 'error.txt'), message, 'utf8');
  } catch {
    /* ignore */
  }
  process.stderr.write(`${message}\n`);
  app.exit(1);
});
