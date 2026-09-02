#!/usr/bin/env node
/**
 * Build macOS .app (PyInstaller onedir/windowed) and a DMG (unsigned).
 * Target: Apple Silicon (arm64) on the build machine.
 */

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DIST_DIR = path.join(ROOT, "dist");
const BUILD_DIR = path.join(ROOT, ".build");
const PYI_DIST = path.join(BUILD_DIR, "pyinstaller-dist-macos");
const PYI_WORK = path.join(BUILD_DIR, "pyinstaller-work-macos");
const BRANDING_DIR = path.join(ROOT, "pdf_editor", "branding");
const SOURCE_LOGO = path.join(ROOT, "assets", "source_logo.png");
const APP_ICON_ICNS = path.join(BRANDING_DIR, "app_icon.icns");
const APP_ICON_PNG = path.join(BRANDING_DIR, "app_icon.png");
const APP_LOGO = path.join(BRANDING_DIR, "app_logo.png");
const MAX_RELEASES = 3;

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

function log(msg) {
  console.log(`[build-macos] ${msg}`);
}

function ocrModelFiles() {
  const dir = path.join(ROOT, "ocr", "models");
  return [
    path.join(dir, "det.onnx"),
    path.join(dir, "rec_korean.onnx"),
    path.join(dir, "rec_korean.yml"),
  ];
}

function ensureOcrModels() {
  run(
    `"${PYTHON}" -c "from pdf_editor.ocr_models import download_ocr_models; download_ocr_models()"`,
  );
  for (const file of ocrModelFiles()) {
    if (!fs.existsSync(file)) {
      throw new Error(`OCR model missing after download: ${file}`);
    }
  }
  log("verified OCR models");
}

function ocrModelDatas() {
  return ocrModelFiles().map((file) => [file, "ocr/models"]);
}

function resolvePython() {
  const candidates = [
    process.env.PYTHON,
    path.join(ROOT, ".venv", "bin", "python"),
    path.join(process.env.HOME || "", ".local", "bin", "python3.12"),
    "python3.12",
    "python3",
  ].filter(Boolean);

  for (const candidate of candidates) {
    try {
      const version = execSync(`"${candidate}" -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"`, {
        encoding: "utf8",
        cwd: ROOT,
      }).trim();
      const [major, minor] = version.split(".").map(Number);
      if (major > 3 || (major === 3 && minor >= 10)) {
        return candidate;
      }
      log(`skip ${candidate} (Python ${version}; need >= 3.10)`);
    } catch {
      // try next
    }
  }
  throw new Error(
    "Python 3.10+ not found. Create .venv with python3.12 or set PYTHON=...",
  );
}

const PYTHON = resolvePython();

function run(cmd, options = {}) {
  log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", cwd: ROOT, ...options });
}

function sanitizeFileName(name) {
  return name.replace(/[<>:"/\\|?*]/g, "_").trim() || "app";
}

function readAppVersion() {
  const versionPath = path.join(ROOT, "pdf_editor", "version.py");
  const source = fs.readFileSync(versionPath, "utf8");
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  if (!match) {
    throw new Error(`Could not parse __version__ from ${versionPath}`);
  }
  return match[1];
}

function readAppBuildStamp() {
  const versionPath = path.join(ROOT, "pdf_editor", "version.py");
  const source = fs.readFileSync(versionPath, "utf8");
  const match = source.match(/APP_BUILD_STAMP\s*=\s*"([^"]*)"/);
  return match?.[1]?.trim() || "";
}

function readReleaseBaseName() {
  return sanitizeFileName(`Tiny PDF Editor v${readAppVersion()}`);
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
  return formatTimestamp();
}

function stampBuildId(stamp) {
  process.env.TINY_BUILD_STAMP = stamp;
  run(`node scripts/sync-version.mjs --stamp=${stamp}`);
}

function invalidatePyInstallerIfBuildIdChanged() {
  const version = readAppVersion();
  const buildStamp = readAppBuildStamp();
  const key = `${version}|${buildStamp}`;
  const stampPath = path.join(PYI_WORK, "embedded-app-version.txt");
  const previous = fs.existsSync(stampPath)
    ? fs.readFileSync(stampPath, "utf8").trim()
    : "";
  if (previous === key) {
    return;
  }
  for (const stale of [PYI_DIST, PYI_WORK]) {
    fs.rmSync(stale, { recursive: true, force: true });
  }
  fs.mkdirSync(PYI_WORK, { recursive: true });
  fs.writeFileSync(stampPath, `${key}\n`, "utf8");
  log(
    `app build id changed (${previous || "none"} -> ${key}); forcing PyInstaller rebuild`,
  );
}

function ensurePythonDeps() {
  try {
    execSync(
      `"${PYTHON}" -c "import PyInstaller, fitz, PyQt6, openpyxl, PIL, numpy"`,
      { cwd: ROOT, stdio: "ignore" },
    );
    log("python dependencies already available");
    return;
  } catch {
    // install below
  }

  try {
    run(`"${PYTHON}" -m pip install -r requirements.txt pyinstaller pyinstaller-hooks-contrib pillow numpy --quiet`);
  } catch {
    // uv-managed venvs may not include pip
    const uv = path.join(process.env.HOME || "", ".local", "bin", "uv");
    if (fs.existsSync(uv)) {
      run(`"${uv}" pip install -r requirements.txt pyinstaller pyinstaller-hooks-contrib pillow numpy --python "${PYTHON}"`);
      return;
    }
    throw new Error(
      "Could not install Python deps (pip missing). Use: uv pip install -r requirements.txt pyinstaller pillow numpy",
    );
  }
}

function ensureBrandingAssets() {
  if (fs.existsSync(SOURCE_LOGO)) {
    run(`"${PYTHON}" scripts/prepare-branding.py`);
  }
  if (!fs.existsSync(APP_LOGO) || !fs.existsSync(APP_ICON_PNG)) {
    throw new Error(
      "Branding assets missing. Run: python scripts/prepare-branding.py",
    );
  }
  if (!fs.existsSync(APP_ICON_ICNS)) {
    throw new Error(
      "app_icon.icns missing. Ensure iconutil is available and re-run prepare-branding.py",
    );
  }
}

function toSpecPath(filePath) {
  return path.resolve(filePath).replace(/\\/g, "/");
}

function writePyInstallerSpec({ root, mainPy, appIcon, datas }) {
  const specPath = path.join(BUILD_DIR, "PDFEditor-macos.spec");
  const dataEntries = datas
    .map(
      ([source, dest]) =>
        `    (${JSON.stringify(toSpecPath(source))}, ${JSON.stringify(dest)}),`,
    )
    .join("\n");

  const appName = "Tiny PDF Editor";
  const spec = `# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

binaries = []
datas = [
${dataEntries}
]
hiddenimports = ["fitz", "socket", "onnxruntime"]

tmp_ret = collect_all("PyQt6")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

tmp_ret = collect_all("pymupdf")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

tmp_ret = collect_all("onnxruntime")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

excludes = [
    "multiprocessing",
    "torch",
    "torchvision",
    "torchaudio",
    "functorch",
    "scipy",
    "onnx",
    "pandas",
    "pyhwpx",
    "sklearn",
    "scikit-learn",
    "tensorflow",
    "IPython",
    "jupyter",
    "matplotlib",
    "cv2",
    "sympy",
    "networkx",
    "fsspec",
    "tqdm",
    "numba",
    "pyarrow",
]

a = Analysis(
    [${JSON.stringify(toSpecPath(mainPy))}],
    pathex=[${JSON.stringify(toSpecPath(root))}],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[${JSON.stringify(toSpecPath(path.join(ROOT, "scripts", "pyi_rth_pyqt6_path.py")))}],
    excludes=excludes,
    noarchive=False,
)

a.scripts = [
    script
    for script in a.scripts
    if "pyi_rth_multiprocessing" not in script[0]
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=${JSON.stringify(appName)},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=${JSON.stringify(toSpecPath(appIcon))},
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=${JSON.stringify(appName)},
)

app = BUNDLE(
    coll,
    name=${JSON.stringify(`${appName}.app`)},
    icon=${JSON.stringify(toSpecPath(appIcon))},
    bundle_identifier="com.note4all.tinypdfeditor",
    info_plist={
        "CFBundleDisplayName": ${JSON.stringify(appName)},
        "CFBundleName": ${JSON.stringify(appName)},
        "CFBundleShortVersionString": ${JSON.stringify(readAppVersion())},
        "CFBundleVersion": ${JSON.stringify(readAppBuildStamp() || readAppVersion())},
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
`;

  fs.mkdirSync(BUILD_DIR, { recursive: true });
  fs.writeFileSync(specPath, spec, "utf8");
  return specPath;
}

function assertNoBloatPackages(appDir) {
  const candidates = [
    path.join(appDir, "Contents", "Frameworks"),
    path.join(appDir, "Contents", "Resources"),
    path.join(appDir, "Contents", "MacOS"),
  ];
  const banned = [
    "torch",
    "torchvision",
    "torchaudio",
    "scipy",
    "pandas",
    "pyhwpx",
  ];
  const found = [];
  for (const base of candidates) {
    if (!fs.existsSync(base)) {
      continue;
    }
    for (const name of banned) {
      if (fs.existsSync(path.join(base, name))) {
        found.push(name);
      }
    }
  }
  if (found.length > 0) {
    throw new Error(
      `PyInstaller bundle still contains unused packages: ${[...new Set(found)].join(", ")}`,
    );
  }
  log("verified no unused ML/science packages in bundle");
}

function buildMacApp() {
  fs.mkdirSync(PYI_DIST, { recursive: true });
  fs.mkdirSync(PYI_WORK, { recursive: true });

  ensureBrandingAssets();
  ensureOcrModels();

  const datas = [
    [APP_LOGO, "pdf_editor/branding"],
    [APP_ICON_PNG, "pdf_editor/branding"],
    [APP_ICON_ICNS, "pdf_editor/branding"],
    ...ocrModelDatas(),
  ];

  const specPath = writePyInstallerSpec({
    root: ROOT,
    mainPy: path.join(ROOT, "main.py"),
    appIcon: APP_ICON_ICNS,
    datas,
  });

  run(
    `"${PYTHON}" -m PyInstaller --noconfirm "${specPath}" --distpath "${PYI_DIST}" --workpath "${PYI_WORK}"`,
  );

  const appDir = path.join(PYI_DIST, "Tiny PDF Editor.app");
  if (!fs.existsSync(appDir)) {
    throw new Error(`PyInstaller output not found: ${appDir}`);
  }
  assertNoBloatPackages(appDir);
  return appDir;
}

function copyDistributionDocs(targetDir) {
  const docs = [
    ["LICENSE", path.join(ROOT, "LICENSE")],
    ["README.md", path.join(ROOT, "README.md")],
    ["DISTRIBUTE.md", path.join(ROOT, "DISTRIBUTE.md")],
  ];
  for (const [name, src] of docs) {
    if (!fs.existsSync(src)) {
      continue;
    }
    fs.copyFileSync(src, path.join(targetDir, name));
  }
}

function removePath(targetPath) {
  fs.rmSync(targetPath, { recursive: true, force: true });
}

/**
 * Copy an .app bundle while preserving relative symlinks.
 * Node fs.cpSync rewrites relative links to absolute /Users/... paths,
 * which break on any machine other than the build host.
 */
function copyAppBundle(srcApp, destApp) {
  removePath(destApp);
  fs.mkdirSync(path.dirname(destApp), { recursive: true });
  // -a keeps symlink text as-is (relative targets stay relative).
  run(`cp -a ${JSON.stringify(srcApp)} ${JSON.stringify(destApp)}`);
  assertPortableSymlinks(destApp);
}

function assertPortableSymlinks(appDir) {
  const bad = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isSymbolicLink()) {
        const target = fs.readlinkSync(full);
        if (path.isAbsolute(target) && !target.startsWith("/Applications")) {
          bad.push(`${path.relative(appDir, full)} -> ${target}`);
        }
      } else if (entry.isDirectory()) {
        walk(full);
      }
    }
  };
  walk(appDir);
  if (bad.length > 0) {
    const preview = bad.slice(0, 5).join("\n  ");
    throw new Error(
      `App bundle has ${bad.length} absolute symlink(s) that will break on other Macs:\n  ${preview}`,
    );
  }
  log("verified portable (relative) symlinks in app bundle");
}

function listReleaseFolders() {
  if (!fs.existsSync(DIST_DIR)) {
    return [];
  }
  const rootName = readReleaseBaseName();
  const pattern = new RegExp(
    `^${rootName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}_\\d{6}_\\d{6}$`,
  );
  return fs
    .readdirSync(DIST_DIR, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && pattern.test(entry.name))
    .map((entry) => ({
      name: entry.name,
      fullPath: path.join(DIST_DIR, entry.name),
      timestamp: entry.name.match(/_(\d{6}_\d{6})$/)?.[1] ?? null,
      mtime: fs.statSync(path.join(DIST_DIR, entry.name)).mtimeMs,
    }));
}

function pruneReleases() {
  const folders = listReleaseFolders();
  const timestamps = [
    ...new Set(folders.map((folder) => folder.timestamp).filter(Boolean)),
  ].sort((a, b) => b.localeCompare(a));
  const keep = new Set(timestamps.slice(0, MAX_RELEASES));
  for (const folder of folders) {
    if (folder.timestamp && !keep.has(folder.timestamp)) {
      removePath(folder.fullPath);
      log(`removed old release: ${folder.name}`);
    }
  }
  for (const name of fs.existsSync(DIST_DIR) ? fs.readdirSync(DIST_DIR) : []) {
    const dmgMatch = name.match(/_(\d{6}_\d{6})\.dmg$/);
    if (dmgMatch && !keep.has(dmgMatch[1])) {
      removePath(path.join(DIST_DIR, name));
      log(`removed old dmg: ${name}`);
    }
  }
  return [...keep];
}

function createDmg(appSource, releaseDir, releaseName) {
  const staging = path.join(BUILD_DIR, "dmg-staging");
  removePath(staging);
  fs.mkdirSync(staging, { recursive: true });

  const stagedApp = path.join(staging, "Tiny PDF Editor.app");
  copyAppBundle(appSource, stagedApp);
  copyDistributionDocs(staging);

  try {
    fs.symlinkSync("/Applications", path.join(staging, "Applications"));
  } catch {
    // optional convenience link
  }

  const dmgPath = path.join(DIST_DIR, `${releaseName}.dmg`);
  if (fs.existsSync(dmgPath)) {
    removePath(dmgPath);
  }

  run(
    `hdiutil create -volname ${JSON.stringify("Tiny PDF Editor")} -srcfolder ${JSON.stringify(staging)} -ov -format UDZO ${JSON.stringify(dmgPath)}`,
  );
  return dmgPath;
}

function main() {
  if (process.platform !== "darwin") {
    throw new Error("macOS 빌드는 darwin에서만 실행할 수 있습니다.");
  }

  const timestamp = resolveBuildStamp();
  if (process.env.TINY_SKIP_STAMP !== "1") {
    stampBuildId(timestamp);
  } else {
    run("node scripts/sync-version.mjs");
  }
  log(`build stamp: ${timestamp}`);

  ensurePythonDeps();
  invalidatePyInstallerIfBuildIdChanged();
  const builtApp = buildMacApp();

  const rootName = readReleaseBaseName();
  const releaseName = `${rootName}_${timestamp}`;
  const releaseDir = path.join(DIST_DIR, releaseName);

  fs.mkdirSync(DIST_DIR, { recursive: true });
  if (fs.existsSync(releaseDir)) {
    removePath(releaseDir);
  }
  fs.mkdirSync(releaseDir, { recursive: true });
  copyAppBundle(builtApp, path.join(releaseDir, "Tiny PDF Editor.app"));
  copyDistributionDocs(releaseDir);

  // Convenience copy at dist root for local testing
  const distApp = path.join(DIST_DIR, "Tiny PDF Editor.app");
  copyAppBundle(builtApp, distApp);

  const dmgPath = createDmg(builtApp, releaseDir, releaseName);

  const kept = pruneReleases();

  log(`release folder: ${releaseDir}`);
  log(`app: ${path.join(releaseDir, "Tiny PDF Editor.app")}`);
  log(`dmg: ${dmgPath}`);
  log(`kept releases (max ${MAX_RELEASES}): ${kept.join(", ") || "(none)"}`);
  log(
    "서명되지 않은 빌드입니다. 최초 실행 시 제어클릭 → 열기, 또는 시스템 설정 → 개인정보 보호 및 보안에서 허용하세요.",
  );
  log("done");
}

if (isMain) {
  try {
    main();
  } catch (error) {
    console.error("[build-macos] failed:", error.message ?? error);
    process.exit(1);
  }
}
