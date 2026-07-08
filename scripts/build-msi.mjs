#!/usr/bin/env node
/**
 * Build per-user Windows MSI with HKCU PDF file association.
 * Requires WiX CLI 7+ (winget install WiXToolset.WiXCLI) and: wix eula accept wix7
 */

import { execSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildPortableApp, ensurePythonDeps, finalizePortableAppBundle } from "./build-dist.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const PYI_DIST = path.join(ROOT, ".build", "pyinstaller-dist");
const STAGE_NAME = "Tiny PDF Editor";
const STAGE_DIR = path.join(ROOT, "msi", STAGE_NAME);
const MSI_DIR = path.join(ROOT, "msi");
const PRODUCT_WXS = path.join(MSI_DIR, "Product.wxs");
const EXE_NAME = "Tiny PDF Editor.exe";
let wixCmd = "wix";

function log(msg) {
  console.log(`[msi] ${msg}`);
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

function toMsiVersion(version) {
  const parts = version.split(".");
  while (parts.length < 4) {
    parts.push("0");
  }
  return parts.slice(0, 4).join(".");
}

function formatTimestamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  const yy = String(date.getFullYear()).slice(2);
  return `${yy}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function resolveWixCmd() {
  try {
    execSync("wix --version", { stdio: "pipe" });
    return "wix";
  } catch {
    // winget default install path when WiX is not on PATH
  }

  const programFiles = process.env["ProgramFiles"] ?? "C:\\Program Files";
  const candidates = [
    path.join(programFiles, "WiX Toolset v7.0", "bin", "wix.exe"),
    path.join(programFiles, "WiX Toolset v6.0", "bin", "wix.exe"),
  ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return `"${candidate}"`;
    }
  }

  throw new Error(
    "WiX CLI not found. Install: winget install WiXToolset.WiXCLI\nThen run: wix eula accept wix7",
  );
}

function ensureWix() {
  wixCmd = resolveWixCmd();
  execSync(`${wixCmd} --version`, { stdio: "pipe" });
}

function stageForMsi() {
  const builtDir = path.join(PYI_DIST, "PDFEditor");
  const builtExe = path.join(builtDir, "PDFEditor.exe");
  if (!fs.existsSync(builtExe)) {
    throw new Error(`PyInstaller output not found: ${builtExe}`);
  }

  fs.rmSync(STAGE_DIR, { recursive: true, force: true });
  fs.cpSync(builtDir, STAGE_DIR, { recursive: true });
  fs.renameSync(
    path.join(STAGE_DIR, "PDFEditor.exe"),
    path.join(STAGE_DIR, EXE_NAME),
  );
  finalizePortableAppBundle(STAGE_DIR);
  log(`staged: ${STAGE_DIR}`);
}

function buildMsi() {
  const version = readVersion();
  const productVersion = toMsiVersion(version);
  const productCode = randomUUID().toUpperCase();
  const timestamp = formatTimestamp();
  const outputName = `Tiny PDF Editor v${version}_${timestamp}.msi`;
  const outputPath = path.join(MSI_DIR, outputName);

  fs.mkdirSync(MSI_DIR, { recursive: true });
  fs.rmSync(outputPath, { force: true });

  run(
    `${wixCmd} build "${PRODUCT_WXS}" -d ProductVersion=${productVersion} -d ProductCode=${productCode} -bindpath "${MSI_DIR}" -ext WixToolset.UI.wixext -o "${outputPath}"`,
  );

  const sizeMb = (fs.statSync(outputPath).size / (1024 * 1024)).toFixed(1);
  log(`output: ${outputPath} (${sizeMb} MB)`);
}

function cleanupStage() {
  fs.rmSync(STAGE_DIR, { recursive: true, force: true });
  log("removed staging folder");
}

function main() {
  ensureWix();
  run("node scripts/sync-version.mjs");
  ensurePythonDeps();
  buildPortableApp();
  stageForMsi();

  try {
    buildMsi();
  } finally {
    cleanupStage();
  }

  log("설치: msi 폴더의 .msi 파일을 더블 클릭하세요 (관리자 권한 불필요).");
  log("done");
}

try {
  main();
} catch (error) {
  console.error("[msi] failed:", error.message ?? error);
  process.exit(1);
}
