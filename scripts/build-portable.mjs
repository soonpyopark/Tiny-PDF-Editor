#!/usr/bin/env node
/**
 * Build a portable zip (same PyInstaller onedir as MSI) into msi/.
 * Output: Tiny PDF Editor vX.Y.Z_YYMMDD_HHMMSS_portable.zip
 * Uses 7-Zip on this PC (PATH or default install location).
 */

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildPortableApp,
  ensurePythonDeps,
  finalizePortableAppBundle,
} from "./build-dist.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const PYI_DIST = path.join(ROOT, ".build", "pyinstaller-dist");
const MSI_DIR = path.join(ROOT, "msi");
const STAGE_ROOT = path.join(ROOT, ".build", "portable-zip-stage");

function log(msg) {
  console.log(`[portable] ${msg}`);
}

function run(cmd, options = {}) {
  log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", cwd: ROOT, ...options });
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

function formatTimestamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  const yy = String(date.getFullYear()).slice(2);
  return `${yy}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function resolve7zCmd() {
  try {
    execSync("7z", { stdio: "pipe" });
    return "7z";
  } catch {
    // fall through to default install paths
  }

  const candidates = [
    path.join(process.env["ProgramFiles"] ?? "C:\\Program Files", "7-Zip", "7z.exe"),
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

function copyDistributionDocs(targetDir) {
  for (const name of ["LICENSE", "README.md", "DISTRIBUTE.md"]) {
    const src = path.join(ROOT, name);
    if (!fs.existsSync(src)) {
      continue;
    }
    fs.copyFileSync(src, path.join(targetDir, name));
  }
}

function stagePortableFolder(releaseName, exeName) {
  const builtDir = path.join(PYI_DIST, "PDFEditor");
  const builtExe = path.join(builtDir, "PDFEditor.exe");
  if (!fs.existsSync(builtExe)) {
    throw new Error(`PyInstaller output not found: ${builtExe}`);
  }

  fs.rmSync(STAGE_ROOT, { recursive: true, force: true });
  const releaseDir = path.join(STAGE_ROOT, releaseName);
  fs.mkdirSync(STAGE_ROOT, { recursive: true });
  fs.cpSync(builtDir, releaseDir, { recursive: true });
  fs.renameSync(path.join(releaseDir, "PDFEditor.exe"), path.join(releaseDir, exeName));
  finalizePortableAppBundle(releaseDir);
  copyDistributionDocs(releaseDir);
  log(`staged: ${releaseDir}`);
  return releaseDir;
}

function zipPortable(sevenZip, releaseName, zipPath) {
  fs.mkdirSync(MSI_DIR, { recursive: true });
  fs.rmSync(zipPath, { force: true });

  // Archive the release folder so unzip yields a single top-level directory.
  const cmd =
    `${sevenZip} a -tzip -mx=9 -y "${zipPath}" "${releaseName}"`;
  log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", cwd: STAGE_ROOT });

  const sizeMb = (fs.statSync(zipPath).size / (1024 * 1024)).toFixed(1);
  log(`output: ${zipPath} (${sizeMb} MB)`);
}

function cleanupStage() {
  fs.rmSync(STAGE_ROOT, { recursive: true, force: true });
  log("removed staging folder");
}

function main() {
  const sevenZip = resolve7zCmd();
  run("node scripts/sync-version.mjs");
  ensurePythonDeps();
  buildPortableApp();

  const version = readVersion();
  const timestamp = formatTimestamp();
  const releaseName = `Tiny PDF Editor v${version}_${timestamp}`;
  const exeName = `${releaseName}.exe`;
  const zipName = `${releaseName}_portable.zip`;
  const zipPath = path.join(MSI_DIR, zipName);

  stagePortableFolder(releaseName, exeName);
  try {
    zipPortable(sevenZip, releaseName, zipPath);
  } finally {
    cleanupStage();
  }

  log("배포: msi 폴더의 *_portable.zip 을 압축 해제한 뒤 폴더 안의 exe를 실행하세요.");
  log("done");
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  try {
    main();
  } catch (error) {
    console.error("[portable] failed:", error.message ?? error);
    process.exit(1);
  }
}
