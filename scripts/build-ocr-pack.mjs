#!/usr/bin/env node
/**
 * Build a sidecar OCR pack zip.
 * Windows: msi/OCR PACK_vX.Y.Z_stamp.zip  (ocr_helper.exe)
 * macOS:   dist/OCR PACK_macOS_vX.Y.Z_stamp.zip  (ocr_helper)
 *
 * Env:
 *   TINY_BUILD_STAMP=YYMMDD_HHMMSS
 *   TINY_USE_APP_STAMP=1
 *   TINY_OCR_OUT_DIR=path
 */

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const BUILD_DIR = path.join(ROOT, ".build");
const VENV_DIR = path.join(BUILD_DIR, "ocr-venv");
const PYI_DIST = path.join(BUILD_DIR, "ocr-pyinstaller-dist");
const PYI_WORK = path.join(BUILD_DIR, "ocr-pyinstaller-work");
const MODELS_DIR = path.join(BUILD_DIR, "ocr-models");
const STAGE_ROOT = path.join(BUILD_DIR, "ocr-zip-stage2");
const MSI_DIR = path.join(ROOT, "msi");
const DIST_DIR = path.join(ROOT, "dist");
const HELPER_DIR = path.join(ROOT, "tools", "ocr_helper");
const REQUIREMENTS = path.join(HELPER_DIR, "requirements-ocr.txt");
const HELPER_PY = path.join(HELPER_DIR, "ocr_helper.py");
const DOWNLOAD_PY = path.join(HELPER_DIR, "download_models.py");
const IS_DARWIN = process.platform === "darwin";
const HELPER_BIN = IS_DARWIN ? "ocr_helper" : "ocr_helper.exe";

function log(msg) {
  console.log(`[ocr-pack] ${msg}`);
}

function run(cmd, options = {}) {
  log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", cwd: ROOT, shell: true, ...options });
}

function readVersion() {
  const versionPath = path.join(ROOT, "pdf_editor", "version.py");
  const source = fs.readFileSync(versionPath, "utf8");
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  if (!match) {
    throw new Error(`Could not parse __version__ from ${versionPath}`);
  }
  return match[1];
}

function readAppStamp() {
  const versionPath = path.join(ROOT, "pdf_editor", "version.py");
  const source = fs.readFileSync(versionPath, "utf8");
  const match = source.match(/APP_BUILD_STAMP\s*=\s*"([^"]+)"/);
  return match ? match[1] : "";
}

function formatTimestamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  const yy = String(date.getFullYear()).slice(2);
  return `${yy}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function resolveBuildStamp() {
  const fromEnv = String(process.env.TINY_BUILD_STAMP || "").trim();
  if (/^\d{6}_\d{6}$/.test(fromEnv)) {
    return fromEnv;
  }
  if (
    process.env.TINY_USE_APP_STAMP === "1" ||
    process.argv.includes("--use-app-stamp")
  ) {
    const stamp = readAppStamp();
    if (/^\d{6}_\d{6}$/.test(stamp)) {
      return stamp;
    }
  }
  return formatTimestamp();
}

function resolveOutputDir() {
  const fromEnv = String(process.env.TINY_OCR_OUT_DIR || "").trim();
  if (fromEnv) {
    return path.resolve(fromEnv);
  }
  return IS_DARWIN ? DIST_DIR : MSI_DIR;
}

function packBaseName(version, stamp) {
  const tag = IS_DARWIN ? "OCR PACK_macOS" : "OCR PACK";
  return `${tag}_v${version}_${stamp}`;
}

function resolve7zCmd() {
  try {
    execSync("7z", { stdio: "pipe" });
    return "7z";
  } catch {
    // fall through
  }
  const candidates = [
    path.join(process.env.ProgramFiles ?? "C:\\Program Files", "7-Zip", "7z.exe"),
    path.join(
      process.env["ProgramFiles(x86)"] ?? "C:\\Program Files (x86)",
      "7-Zip",
      "7z.exe",
    ),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return `"${candidate}"`;
    }
  }
  throw new Error(
    "7-Zip(7z.exe)를 찾을 수 없습니다. 설치 후 PATH에 추가하거나 기본 경로에 두세요.\n" +
      "예: C:\\Program Files\\7-Zip\\7z.exe",
  );
}

function hostPython() {
  if (IS_DARWIN) {
    return process.env.PYTHON || "python3";
  }
  return "python";
}

function venvPythonPath() {
  const win = path.join(VENV_DIR, "Scripts", "python.exe");
  if (fs.existsSync(win)) {
    return win;
  }
  const unix = path.join(VENV_DIR, "bin", "python");
  if (fs.existsSync(unix)) {
    return unix;
  }
  return "";
}

function venvPython() {
  const found = venvPythonPath();
  if (!found) {
    throw new Error(`OCR venv Python not found in ${VENV_DIR}`);
  }
  return `"${found}"`;
}

function ensureOcrVenv() {
  if (!venvPythonPath()) {
    run(`${hostPython()} -m venv "${VENV_DIR}"`);
  }
  if (process.argv.includes("--skip-deps") && venvPythonPath()) {
    log("skip venv package install (--skip-deps)");
    return;
  }
  run(`${venvPython()} -m pip install --upgrade pip`);
  run(`${venvPython()} -m pip install --upgrade -r "${REQUIREMENTS}"`);
}

function toSpecPath(filePath) {
  return path.resolve(filePath).replace(/\\/g, "/");
}

function writeHelperSpec() {
  const specPath = path.join(BUILD_DIR, "ocr_helper.spec");
  const useUpx = !IS_DARWIN;
  const spec = `# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

binaries = []
datas = []
hiddenimports = []

for package in ("rapidocr", "onnxruntime", "cv2", "PIL"):
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

hiddenimports += [
    "numpy",
    "pyclipper",
    "shapely",
    "shapely.geometry",
    "PIL.Image",
    "cv2",
]

excludes = [
    "paddle",
    "paddleocr",
    "paddlepaddle",
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "openvino",
    "tensorrt",
    "mnn",
    "IPython",
    "jupyter",
    "matplotlib",
    "pandas",
    "sklearn",
    "scipy",
    "PyQt6",
    "tkinter",
]

a = Analysis(
    [${JSON.stringify(toSpecPath(HELPER_PY))}],
    pathex=[${JSON.stringify(toSpecPath(ROOT))}],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ocr_helper",
    debug=False,
    strip=False,
    upx=${useUpx ? "True" : "False"},
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=${useUpx ? "True" : "False"},
    upx_exclude=[],
    name="ocr_helper",
)
`;
  fs.mkdirSync(BUILD_DIR, { recursive: true });
  fs.writeFileSync(specPath, spec, "utf8");
  return specPath;
}

function buildHelperDir() {
  fs.rmSync(PYI_DIST, { recursive: true, force: true });
  fs.rmSync(PYI_WORK, { recursive: true, force: true });
  const specPath = writeHelperSpec();
  run(
    `${venvPython()} -m PyInstaller --noconfirm --clean --distpath "${PYI_DIST}" --workpath "${PYI_WORK}" "${specPath}"`,
  );
  const binary = path.join(PYI_DIST, "ocr_helper", HELPER_BIN);
  if (!fs.existsSync(binary)) {
    throw new Error(`${HELPER_BIN} not found: ${binary}`);
  }
  if (IS_DARWIN) {
    try {
      fs.chmodSync(binary, 0o755);
    } catch {
      // ignore
    }
  }
  return path.join(PYI_DIST, "ocr_helper");
}

function writePackReadme(targetDir, version, stamp) {
  const text = [
    "Tiny PDF Editor OCR 팩",
    "====================",
    "",
    `버전: ${version}`,
    `빌드: ${stamp}`,
    IS_DARWIN ? "플랫폼: macOS" : "플랫폼: Windows",
    "언어: 한국어 + 한자 + 영어",
    "",
    "OCR 폴더에서 이 zip을 「여기에 풀기」하면 됩니다.",
    "",
    `  ${HELPER_BIN}`,
    "  _internal/",
    "  models/          (한글·한자·영어 인식 모델)",
    "  VERSION.txt",
    "",
    "앱을 다시 실행하거나 OCR 메뉴를 다시 열면 인식이 켜집니다.",
    "",
  ].join("\n");
  fs.writeFileSync(
    path.join(targetDir, "여기에 OCR 구성 요소를 넣으세요.txt"),
    text,
    "utf8",
  );
  fs.writeFileSync(
    path.join(targetDir, "VERSION.txt"),
    `${version}_${stamp}\nplatform=${IS_DARWIN ? "macos" : "windows"}\nlangs=korean,en,ch\n`,
    "utf8",
  );
}

function stagePack(helperDir, version, stamp) {
  fs.rmSync(STAGE_ROOT, { recursive: true, force: true });
  fs.mkdirSync(STAGE_ROOT, { recursive: true });
  fs.cpSync(helperDir, STAGE_ROOT, { recursive: true });
  fs.cpSync(MODELS_DIR, path.join(STAGE_ROOT, "models"), { recursive: true });
  writePackReadme(STAGE_ROOT, version, stamp);
  log(`staged: ${STAGE_ROOT}`);
  return STAGE_ROOT;
}

function zipPack(zipPath) {
  fs.mkdirSync(path.dirname(zipPath), { recursive: true });
  fs.rmSync(zipPath, { force: true });
  if (IS_DARWIN) {
    const cmd = `ditto -c -k --norsrc --noextattr . ${JSON.stringify(zipPath)}`;
    log(`> ${cmd}`);
    execSync(cmd, { stdio: "inherit", cwd: STAGE_ROOT, shell: true });
  } else {
    const sevenZip = resolve7zCmd();
    const cmd = `${sevenZip} a -tzip -mx=9 -y "${zipPath}" *`;
    log(`> ${cmd}`);
    execSync(cmd, { stdio: "inherit", cwd: STAGE_ROOT, shell: true });
  }
  const sizeMb = (fs.statSync(zipPath).size / (1024 * 1024)).toFixed(1);
  log(`output: ${zipPath} (${sizeMb} MB)`);
}

/**
 * @param {{ stamp?: string, outputDir?: string }} [options]
 * @returns {string} zip path
 */
export function buildOcrPack(options = {}) {
  const stamp = options.stamp || resolveBuildStamp();
  const version = readVersion();
  const outDir = options.outputDir
    ? path.resolve(options.outputDir)
    : resolveOutputDir();
  const zipPath = path.join(outDir, `${packBaseName(version, stamp)}.zip`);
  log(`platform: ${IS_DARWIN ? "macOS" : "Windows"}`);
  log(`build stamp: ${stamp}`);
  log(`output name: ${path.basename(zipPath)}`);

  ensureOcrVenv();
  run(`${venvPython()} "${DOWNLOAD_PY}" --dest "${MODELS_DIR}"`);
  const helperDir = buildHelperDir();
  try {
    stagePack(helperDir, version, stamp);
    zipPack(zipPath);
  } finally {
    fs.rmSync(STAGE_ROOT, { recursive: true, force: true });
  }
  log(
    IS_DARWIN
      ? "배포: dist 폴더의 OCR PACK_macOS_*.zip 을 받아 OCR 폴더에 압축을 푸세요."
      : "배포: msi 폴더의 OCR PACK_*.zip 을 받아 OCR 폴더에 압축을 푸세요.",
  );
  log("done");
  return zipPath;
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  try {
    buildOcrPack();
  } catch (error) {
    console.error("[ocr-pack] failed:", error.message ?? error);
    process.exit(1);
  }
}
