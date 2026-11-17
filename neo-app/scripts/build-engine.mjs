/**
 * PDF 엔진(pdf_editor.engine)을 PyInstaller 로 동결한다 (onedir).
 *
 *   node scripts/build-engine.mjs [--force]
 *
 * 결과: neo-app/.engine-build/dist/tiny-pdf-engine/ (tiny-pdf-engine.exe + _internal/)
 * electron-builder 가 이 폴더를 resources/engine 으로 복사한다 (package.json extraResources).
 * 사용자 PC 에 Python 이 없어도 동작하게 하는 것이 목적이다.
 * 소스·자산이 바뀌지 않았으면 다시 만들지 않는다.
 */
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const NEO = path.resolve(here, '..');
const ROOT = path.resolve(NEO, '..');
const OUT = path.join(NEO, '.engine-build');
const DIST = path.join(OUT, 'dist');
const WORK = path.join(OUT, 'work');
const NAME = 'tiny-pdf-engine';
export const ENGINE_DIR = path.join(DIST, NAME);
const ENGINE_EXE = path.join(ENGINE_DIR, process.platform === 'win32' ? `${NAME}.exe` : NAME);
const STAMP = path.join(OUT, 'stamp.json');

const python = process.env.TINY_PDF_PYTHON || 'python';
const log = (message) => console.log(`[engine] ${message}`);

function run(cmd, args, options = {}) {
  const result = spawnSync(cmd, args, { stdio: 'inherit', cwd: ROOT, ...options });
  if (result.status !== 0) throw new Error(`${cmd} ${args.join(' ')} 실패 (exit ${result.status})`);
}

function toSpec(file) {
  return file.replace(/\\/g, '/');
}

/** 엔진 번들에 영향을 주는 파일들의 내용 해시. */
function sourceHash(extra) {
  const hash = crypto.createHash('sha256');
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === '__pycache__') continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else files.push(full);
    }
  };
  walk(path.join(ROOT, 'pdf_editor'));
  walk(path.join(ROOT, 'ocr'));
  files.push(path.join(NEO, 'engine', 'entry.py'), path.join(here, 'build-engine.mjs'));
  for (const file of files.sort()) {
    hash.update(path.relative(ROOT, file));
    hash.update(fs.readFileSync(file));
  }
  hash.update(extra);
  return hash.digest('hex');
}

function ensureOcrModels() {
  const models = path.join(ROOT, 'ocr', 'models');
  const required = ['det.onnx', 'rec_korean.onnx', 'rec_korean.yml'];
  if (required.every((file) => fs.existsSync(path.join(models, file)))) return;
  log('OCR 모델이 없어 내려받습니다 (scripts/ensure-ocr-models.mjs)');
  run('node', [path.join(ROOT, 'scripts', 'ensure-ocr-models.mjs')]);
}

function writeSpec() {
  const brandingDir = path.join(ROOT, 'pdf_editor', 'branding');
  const brandingFiles = ['app_icon.ico', 'app_icon.png', 'app_logo.png', 'pdf_file_icon.ico'].filter((name) =>
    fs.existsSync(path.join(brandingDir, name)),
  );
  const datas = [
    ...brandingFiles.map((name) => [path.join(brandingDir, name), 'pdf_editor/branding']),
    ...['hwp_to_pdf_helper.exe', 'FilePathCheckerModule.dll']
      .map((name) => path.join(ROOT, 'pdf_editor', 'vendor', name))
      .filter((file) => fs.existsSync(file))
      .map((file) => [file, 'pdf_editor/vendor']),
    ...['det.onnx', 'rec_korean.onnx', 'rec_korean.yml'].map((name) => [
      path.join(ROOT, 'ocr', 'models', name),
      'ocr/models',
    ]),
  ];
  const dataLines = datas.map(([src, dest]) => `    (${JSON.stringify(toSpec(src))}, ${JSON.stringify(dest)}),`).join('\n');

  const spec = `# -*- mode: python ; coding: utf-8 -*-
# build-engine.mjs 가 만든다. 직접 고치지 말고 스크립트를 고친다.
from PyInstaller.utils.hooks import collect_all

binaries = []
datas = [
${dataLines}
]
hiddenimports = ["fitz", "_socket", "socket"]

def _unused(entry):
    # PyMuPDF 의 layout(문서 구조 분석 ONNX 모델 ~30MB)과 C 개발용 파일은 엔진이 쓰지 않는다.
    src = entry[0].replace("\\\\", "/")
    return "/pymupdf/layout/" in src or "/mupdf-devel/" in src

for package in ("pymupdf", "ko_pii", "onnxruntime"):
    d, b, h = collect_all(package)
    datas += [e for e in d if not _unused(e)]
    binaries += [e for e in b if not _unused(e)]
    hiddenimports += [m for m in h if not m.startswith("pymupdf.layout")]

# 엔진이 쓰지 않는 무거운 패키지는 번들에서 뺀다. PyQt6 도 엔진 경로에서는 쓰지 않는다.
excludes = [
    "PyQt6", "PyQt5", "PySide6", "PySide2", "tkinter",
    "multiprocessing",
    "torch", "torchvision", "torchaudio", "functorch", "scipy", "onnx", "pandas", "pyhwpx",
    "sklearn", "tensorflow", "IPython", "jupyter", "matplotlib", "cv2", "sympy", "networkx",
    "fsspec", "tqdm", "numba", "pyarrow",
    "cryptography", "lxml", "pikepdf", "google", "pymupdf4llm", "pymupdf_layout", "pymupdf.layout",
]

a = Analysis(
    [${JSON.stringify(toSpec(path.join(NEO, 'engine', 'entry.py')))}],
    pathex=[${JSON.stringify(toSpec(ROOT))}],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

a.scripts = [s for s in a.scripts if "pyi_rth_multiprocessing" not in s[0]]

# PyInstaller 훅이 위 필터를 거치지 않고 같은 파일을 다시 담는 경우가 있다(PyMuPDF layout ONNX 모델 ~40MB,
# C 개발용 .lib). 분석이 끝난 최종 목록에서 한 번 더 걸러 패키지가 불어나지 않게 한다.
def _unused_toc(entry):
    text = (str(entry[0]) + "|" + str(entry[1])).replace(chr(92), "/")
    return "pymupdf/layout/" in text or "mupdf-devel/" in text

a.datas = [e for e in a.datas if not _unused_toc(e)]
a.binaries = [e for e in a.binaries if not _unused_toc(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=${JSON.stringify(NAME)},
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=[${JSON.stringify(toSpec(path.join(brandingDir, 'app_icon.ico')))}],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=${JSON.stringify(NAME)},
)
`;
  fs.mkdirSync(OUT, { recursive: true });
  const specPath = path.join(OUT, `${NAME}.spec`);
  fs.writeFileSync(specPath, spec, 'utf8');
  return specPath;
}

export function buildEngine({ force = false } = {}) {
  ensureOcrModels();
  const version = spawnSync(python, ['--version'], { encoding: 'utf8' });
  if (version.status !== 0) throw new Error(`Python 을 실행할 수 없습니다: ${python}`);
  const pyi = spawnSync(python, ['-m', 'PyInstaller', '--version'], { encoding: 'utf8' });
  if (pyi.status !== 0) {
    throw new Error('PyInstaller 가 필요합니다: python -m pip install pyinstaller pyinstaller-hooks-contrib');
  }

  const hash = sourceHash(`${version.stdout}${version.stderr}|${pyi.stdout}`);
  if (!force && fs.existsSync(ENGINE_EXE) && fs.existsSync(STAMP)) {
    try {
      if (JSON.parse(fs.readFileSync(STAMP, 'utf8')).hash === hash) {
        log('최신 상태라 다시 만들지 않습니다 (--force 로 강제)');
        return ENGINE_DIR;
      }
    } catch {
      // 스탬프가 깨졌으면 다시 만든다.
    }
  }

  log('PyInstaller 로 엔진을 동결합니다 …');
  const specPath = writeSpec();
  fs.rmSync(ENGINE_DIR, { recursive: true, force: true });
  run(python, ['-m', 'PyInstaller', '--noconfirm', '--clean', specPath, '--distpath', DIST, '--workpath', WORK]);
  if (!fs.existsSync(ENGINE_EXE)) throw new Error(`엔진 실행 파일이 만들어지지 않았습니다: ${ENGINE_EXE}`);
  fs.writeFileSync(STAMP, JSON.stringify({ hash, builtAt: new Date().toISOString() }));
  log(`완료: ${ENGINE_EXE}`);
  return ENGINE_DIR;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    buildEngine({ force: process.argv.includes('--force') });
  } catch (error) {
    console.error(`[engine] ${error.message}`);
    process.exit(1);
  }
}
