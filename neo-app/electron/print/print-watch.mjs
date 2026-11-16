/**
 * 백그라운드 인쇄 감시자.
 *
 * Electron 실행 파일을 ELECTRON_RUN_AS_NODE=1 로 돌려 Chromium 없이 Node 만 띄운다
 * (창·GPU 프로세스가 없어 훨씬 가볍다). 앱이 꺼져 있어도 인쇄 PDF 가 열리도록
 * 스풀 폴더를 계속 지켜보다가, PDF 가 완성되면 앱을 `앱 <pdf>` 로 띄운다.
 * 앱이 이미 떠 있으면 single-instance 로 경로가 그 앱에 전달된다.
 *
 *   node print-watch.mjs --exe <앱 실행 파일> [--app-arg <앱 인자>]...
 */
import { launchEditor, printerInstalled, startSpoolWatcher } from './printSpool.mjs';

function parseArgs(argv) {
  const out = { exe: '', prefixArgs: [] };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--exe') out.exe = argv[(i += 1)] ?? '';
    else if (argv[i] === '--app-arg') out.prefixArgs.push(argv[(i += 1)] ?? '');
  }
  return out;
}

const { exe, prefixArgs } = parseArgs(process.argv.slice(2));

if (!exe) {
  process.exit(2);
}
// 프린터가 없으면 감시할 이유가 없다.
if (!printerInstalled()) {
  process.exit(0);
}

const watcher = startSpoolWatcher({
  onPdf: (pdfPath) => launchEditor({ exe, prefixArgs, pdfPath }),
  onLockLost: () => process.exit(0),
  log: (message) => {
    if (process.env.TINY_PRINT_DEBUG === '1') console.log(`[print-watch] ${message}`);
  },
});

// 다른 감시자가 이미 있으면 조용히 끝난다.
if (!watcher) {
  process.exit(0);
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGBREAK']) {
  process.on(signal, () => {
    watcher.stop();
    process.exit(0);
  });
}
process.on('exit', () => watcher.stop());
