#!/usr/bin/env node
/**
 * Build portable Windows folder with PyInstaller (onedir).
 * --update: patch only changed files into the latest dist release folder.
 */

import { createHash } from "node:crypto";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DIST_DIR = path.join(ROOT, "dist");
const BUILD_DIR = path.join(ROOT, ".build");
const PYI_DIST = path.join(BUILD_DIR, "pyinstaller-dist");
const PYI_WORK = path.join(BUILD_DIR, "pyinstaller-work");
const MANIFEST_PATH = path.join(BUILD_DIR, "latest-release.json");
const BRANDING_DIR = path.join(ROOT, "pdf_editor", "branding");
const APP_ICON = path.join(BRANDING_DIR, "app_icon.ico");
const APP_LOGO = path.join(BRANDING_DIR, "app_logo.png");
const MAX_RELEASES = 3;
const isUpdate = process.argv.includes("--update");

function log(msg) {
  console.log(`[build] ${msg}`);
}

function run(cmd, options = {}) {
  log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", cwd: ROOT, ...options });
}

function sanitizeFileName(name) {
  return name.replace(/[<>:"/\\|?*]/g, "_").trim() || "app";
}

function readReleaseBaseName() {
  const versionPath = path.join(ROOT, "pdf_editor", "version.py");
  const source = fs.readFileSync(versionPath, "utf8");
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  if (!match) {
    throw new Error(`Could not parse __version__ from ${versionPath}`);
  }
  return sanitizeFileName(`Tiny PDF Editor v${match[1]}`);
}

function formatTimestamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  const yy = String(date.getFullYear()).slice(2);
  return `${yy}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function ensurePythonDeps() {
  run("python -m pip install -r requirements.txt pyinstaller --quiet");
}

function buildPortableApp() {
  fs.mkdirSync(PYI_DIST, { recursive: true });
  fs.mkdirSync(PYI_WORK, { recursive: true });

  if (!fs.existsSync(APP_ICON) || !fs.existsSync(APP_LOGO)) {
    throw new Error(
      "Branding assets missing. Run: python scripts/prepare-branding.py",
    );
  }

  const args = [
    "python -m PyInstaller",
    "--noconfirm",
    "--onedir",
    "--windowed",
    '--name "PDFEditor"',
    `--distpath "${PYI_DIST}"`,
    `--workpath "${PYI_WORK}"`,
    `--specpath "${BUILD_DIR}"`,
    `--icon "${APP_ICON}"`,
    `--add-data "${APP_LOGO};pdf_editor/branding"`,
    `--add-data "${APP_ICON};pdf_editor/branding"`,
    "--hidden-import fitz",
    "--collect-all PyQt6",
    "--collect-all pymupdf",
    "main.py",
  ];

  run(args.join(" "));
}

function fileHash(filePath) {
  const data = fs.readFileSync(filePath);
  return createHash("sha256").update(data).digest("hex");
}

function filesEqual(srcPath, destPath) {
  if (!fs.existsSync(destPath)) {
    return false;
  }
  const srcStat = fs.statSync(srcPath);
  const destStat = fs.statSync(destPath);
  if (srcStat.size !== destStat.size) {
    return false;
  }
  if (Math.floor(srcStat.mtimeMs) === Math.floor(destStat.mtimeMs)) {
    return true;
  }
  return fileHash(srcPath) === fileHash(destPath);
}

function copyDistributionDocs(targetDir) {
  const docs = [
    ["LICENSE", path.join(ROOT, "LICENSE")],
    ["README.md", path.join(ROOT, "README.md")],
    ["DISTRIBUTE.md", path.join(ROOT, "DISTRIBUTE.md")],
  ];

  let updated = 0;
  for (const [name, src] of docs) {
    if (!fs.existsSync(src)) {
      continue;
    }
    const dest = path.join(targetDir, name);
    if (!filesEqual(src, dest)) {
      fs.copyFileSync(src, dest);
      log(`updated doc: ${name}`);
      updated += 1;
    }
  }
  return updated;
}

function getReleaseTimestamp(name) {
  const match = name.match(/_(\d{6}_\d{6})$/);
  return match ? match[1] : null;
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
      timestamp: getReleaseTimestamp(entry.name),
      mtime: fs.statSync(path.join(DIST_DIR, entry.name)).mtimeMs,
    }));
}

function getLatestReleaseFolder() {
  if (fs.existsSync(MANIFEST_PATH)) {
    try {
      const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf8"));
      const fromManifest = path.join(DIST_DIR, manifest.releaseName ?? "");
      if (manifest.releaseName && fs.existsSync(fromManifest)) {
        return {
          name: manifest.releaseName,
          fullPath: fromManifest,
          timestamp: getReleaseTimestamp(manifest.releaseName),
        };
      }
    } catch {
      // fall through
    }
  }

  const folders = listReleaseFolders();
  if (!folders.length) {
    return null;
  }

  folders.sort((a, b) => {
    if (a.timestamp && b.timestamp && a.timestamp !== b.timestamp) {
      return b.timestamp.localeCompare(a.timestamp);
    }
    return b.mtime - a.mtime;
  });
  return folders[0];
}

function findReleaseExeName(releaseDir) {
  const rootName = readReleaseBaseName();
  const matches = fs
    .readdirSync(releaseDir)
    .filter((name) => name.endsWith(".exe") && name.startsWith(rootName));
  if (!matches.length) {
    return `${path.basename(releaseDir)}.exe`;
  }
  return matches.sort().reverse()[0];
}

function syncBuiltToRelease(builtDir, releaseDir) {
  const releaseExeName = findReleaseExeName(releaseDir);
  let copied = 0;
  let skipped = 0;

  function mapDestFile(relativePath, fileName) {
    if (!relativePath && fileName === "PDFEditor.exe") {
      return releaseExeName;
    }
    return fileName;
  }

  function walk(relativeDir = "") {
    const currentSrc = path.join(builtDir, relativeDir);
    for (const entry of fs.readdirSync(currentSrc, { withFileTypes: true })) {
      const relPath = relativeDir ? path.join(relativeDir, entry.name) : entry.name;
      const srcPath = path.join(builtDir, relPath);

      if (entry.isDirectory()) {
        const destDirName = mapDestFile(relativeDir, entry.name);
        const destDir = relativeDir
          ? path.join(releaseDir, relativeDir, destDirName)
          : path.join(releaseDir, destDirName);
        fs.mkdirSync(destDir, { recursive: true });
        walk(relPath);
        continue;
      }

      const destFileName = mapDestFile(relativeDir, entry.name);
      const destPath = relativeDir
        ? path.join(releaseDir, relativeDir, destFileName)
        : path.join(releaseDir, destFileName);

      fs.mkdirSync(path.dirname(destPath), { recursive: true });

      if (filesEqual(srcPath, destPath)) {
        skipped += 1;
        continue;
      }

      fs.copyFileSync(srcPath, destPath);
      copied += 1;
      log(`updated: ${relPath === "PDFEditor.exe" ? destFileName : relPath.replace(/\\/g, "/")}`);
    }
  }

  walk();
  return { copied, skipped };
}

function writeManifest(releaseName) {
  fs.mkdirSync(BUILD_DIR, { recursive: true });
  fs.writeFileSync(
    MANIFEST_PATH,
    JSON.stringify(
      {
        releaseName,
        updatedAt: new Date().toISOString(),
      },
      null,
      2,
    ),
    "utf8",
  );
}

function removePath(targetPath) {
  fs.rmSync(targetPath, { recursive: true, force: true });
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

  return [...keep];
}

function cleanupLegacyArtifacts() {
  if (!fs.existsSync(DIST_DIR)) {
    return;
  }

  const rootName = readReleaseBaseName();
  for (const name of fs.readdirSync(DIST_DIR)) {
    const fullPath = path.join(DIST_DIR, name);
    if (name.endsWith(".zip")) {
      removePath(fullPath);
      log(`removed legacy zip: ${name}`);
      continue;
    }

    if (name.endsWith(".exe") && name.startsWith(rootName)) {
      removePath(fullPath);
      log(`removed legacy exe: ${name}`);
      continue;
    }

    if (["LICENSE", "README.md", "DISTRIBUTE.md"].includes(name) && fs.statSync(fullPath).isFile()) {
      removePath(fullPath);
      log(`removed legacy file: ${name}`);
    }
  }
}

function ensureBuiltOutput() {
  const builtDir = path.join(PYI_DIST, "PDFEditor");
  const builtExe = path.join(builtDir, "PDFEditor.exe");
  if (!fs.existsSync(builtExe)) {
    throw new Error(`PyInstaller output not found: ${builtExe}`);
  }
  return builtDir;
}

function mainFull() {
  const rootName = readReleaseBaseName();
  const timestamp = formatTimestamp();
  const releaseName = `${rootName}_${timestamp}`;
  const exeName = `${releaseName}.exe`;
  const builtDir = ensureBuiltOutput();
  const releaseDir = path.join(DIST_DIR, releaseName);

  log(`root: ${rootName}`);
  log(`timestamp: ${timestamp}`);

  fs.mkdirSync(DIST_DIR, { recursive: true });
  cleanupLegacyArtifacts();

  if (fs.existsSync(releaseDir)) {
    removePath(releaseDir);
  }

  fs.cpSync(builtDir, releaseDir, { recursive: true });
  fs.renameSync(path.join(releaseDir, "PDFEditor.exe"), path.join(releaseDir, exeName));
  copyDistributionDocs(releaseDir);

  writeManifest(releaseName);
  log(`release folder: ${releaseDir}`);
  log(`run: ${path.join(releaseDir, exeName)}`);

  const keptSets = pruneReleases();

  log("dist contents:");
  for (const name of fs.readdirSync(DIST_DIR).sort()) {
    console.log(`  - ${name}/`);
  }
  log(`kept releases (max ${MAX_RELEASES}): ${keptSets.join(", ") || "(none)"}`);
  log("USB 사용: dist 안의 폴더 전체를 USB에 복사한 뒤 exe를 실행하세요.");
  log("done");
}

function mainUpdate() {
  const latest = getLatestReleaseFolder();
  if (!latest) {
    log("기존 배포 폴더가 없어 전체 빌드를 실행합니다.");
    return mainFull();
  }

  const builtDir = ensureBuiltOutput();
  const releaseDir = latest.fullPath;

  log(`update target: ${latest.name}`);
  const { copied, skipped } = syncBuiltToRelease(builtDir, releaseDir);
  const docsUpdated = copyDistributionDocs(releaseDir);

  writeManifest(latest.name);

  const exeName = findReleaseExeName(releaseDir);
  log(`release folder: ${releaseDir}`);
  log(`run: ${path.join(releaseDir, exeName)}`);
  log(`files updated: ${copied}, unchanged: ${skipped}, docs updated: ${docsUpdated}`);
  log("done");
}

function main() {
  ensurePythonDeps();
  buildPortableApp();

  if (isUpdate) {
    mainUpdate();
    return;
  }

  mainFull();
}

try {
  main();
} catch (error) {
  console.error("[build] failed:", error.message ?? error);
  process.exit(1);
}
