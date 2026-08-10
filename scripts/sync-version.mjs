#!/usr/bin/env node
/**
 * Sync project version from pdf_editor/version.py into package.json,
 * package-lock.json, README, LICENSE, and MSI license RTF.
 *
 * Optional: TINY_BUILD_STAMP=YYMMDD_HHMMSS (or --stamp=…) writes APP_BUILD_STAMP
 * so MSI/portable filename and in-app update check stay aligned.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const VERSION_PY = path.join(ROOT, "pdf_editor", "version.py");

function readAppVersion() {
  const source = fs.readFileSync(VERSION_PY, "utf8");
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  if (!match) {
    throw new Error(`Could not parse __version__ from ${VERSION_PY}`);
  }
  return match[1];
}

function formatBuildStamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  const yy = String(date.getFullYear()).slice(2);
  return `${yy}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function resolveStampArg() {
  const fromEnv = String(process.env.TINY_BUILD_STAMP || "").trim();
  if (/^\d{6}_\d{6}$/.test(fromEnv)) {
    return fromEnv;
  }
  for (const arg of process.argv.slice(2)) {
    if (arg === "--refresh-stamp") {
      return formatBuildStamp();
    }
    const match = /^--stamp=(.+)$/.exec(arg);
    if (match && /^\d{6}_\d{6}$/.test(match[1].trim())) {
      return match[1].trim();
    }
  }
  return null;
}

function syncBuildStamp(stamp) {
  let text = fs.readFileSync(VERSION_PY, "utf8");
  if (/APP_BUILD_STAMP\s*=\s*"[^"]*"/.test(text)) {
    text = text.replace(
      /APP_BUILD_STAMP\s*=\s*"[^"]*"/,
      `APP_BUILD_STAMP = "${stamp}"`,
    );
  } else {
    text = text.replace(
      /(__version__\s*=\s*"[^"]*"\s*\n)/,
      `$1\nAPP_BUILD_STAMP = "${stamp}"\n`,
    );
  }
  fs.writeFileSync(VERSION_PY, text, "utf8");
  console.log(`[sync-version] APP_BUILD_STAMP -> ${stamp}`);
}

function syncPackageJson(version) {
  const filePath = path.join(ROOT, "package.json");
  const data = JSON.parse(fs.readFileSync(filePath, "utf8"));
  data.version = version;
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

function syncPackageLock(version) {
  const filePath = path.join(ROOT, "package-lock.json");
  if (!fs.existsSync(filePath)) {
    return;
  }
  const data = JSON.parse(fs.readFileSync(filePath, "utf8"));
  data.version = version;
  if (data.packages && data.packages[""]) {
    data.packages[""].version = version;
  }
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

function syncLicense(version) {
  const filePath = path.join(ROOT, "LICENSE");
  let text = fs.readFileSync(filePath, "utf8");
  const header = `Tiny PDF Editor v${version}`;

  if (/^Tiny PDF Editor v[^\n\r]+[\n\r]/m.test(text)) {
    text = text.replace(/^Tiny PDF Editor v[^\n\r]+/m, header);
  } else {
    text = text.replace(/^(MIT License\r?\n\r?\n)/, `$1${header}\n\n`);
  }

  fs.writeFileSync(filePath, text, "utf8");
}

function syncReadme(version) {
  const filePath = path.join(ROOT, "README.md");
  let text = fs.readFileSync(filePath, "utf8");
  const releasePrefix = `Tiny PDF Editor v${version}`;

  text = text.replace(
    /^# Tiny PDF Editor v[^\n]+/m,
    `# Tiny PDF Editor v${version}`,
  );
  text = text.replace(
    /`Tiny PDF [Ee]ditor v[^`_]+_YYMMDD_HHMMSS\.exe`/g,
    `\`${releasePrefix}_YYMMDD_HHMMSS.exe\``,
  );
  text = text.replace(
    /Tiny PDF [Ee]ditor v[^_\n]+_YYMMDD_HHMMSS\//g,
    `${releasePrefix}_YYMMDD_HHMMSS/`,
  );
  text = text.replace(
    /Tiny PDF [Ee]ditor v[^_\n]+_YYMMDD_HHMMSS\.exe/g,
    `${releasePrefix}_YYMMDD_HHMMSS.exe`,
  );
  text = text.replace(
    /`Tiny PDF [Ee]ditor v[^`_]+_YYMMDD_HHMMSS\.msi`/g,
    `\`${releasePrefix}_YYMMDD_HHMMSS.msi\``,
  );
  text = text.replace(
    /Tiny PDF [Ee]ditor v[^_\n]+_YYMMDD_HHMMSS\.msi/g,
    `${releasePrefix}_YYMMDD_HHMMSS.msi`,
  );
  text = text.replace(
    /Tiny PDF [Ee]ditor v[^_\n]+_YYMMDD_HHMMSS_portable\.zip/g,
    `${releasePrefix}_YYMMDD_HHMMSS_portable.zip`,
  );
  text = text.replace(
    /`Tiny PDF [Ee]ditor v[^`_]+_YYMMDD_HHMMSS\.dmg`/g,
    `\`${releasePrefix}_YYMMDD_HHMMSS.dmg\``,
  );
  text = text.replace(
    /Tiny PDF [Ee]ditor v[^_\n]+_YYMMDD_HHMMSS\.dmg/g,
    `${releasePrefix}_YYMMDD_HHMMSS.dmg`,
  );

  fs.writeFileSync(filePath, text, "utf8");
}

function syncMsiLicenseRtf(version) {
  const filePath = path.join(ROOT, "msi", "License.rtf");
  const lines = [
    `Tiny PDF Editor v${version}`,
    "https://note4all.tistory.com",
    "https://github.com/soonpyopark/Tiny-PDF-Editor",
    "",
    "Source code: MIT License. See LICENSE in the installation folder",
    "or the project repository for full terms and third-party notices",
    "(PyMuPDF, PyQt6, openpyxl, ko-pii, and others).",
  ];
  const body = lines.map((line) => `${line}\\par`).join("\n");
  const content =
    "{\\rtf1\\ansi\\ansicpg65001\\deff0{\\fonttbl{\\f0\\fnil\\fcharset0 Segoe UI;}}\n" +
    "\\viewkind4\\uc1\\pard\\sa200\\sl276\\slmult1\\f0\\fs22 " +
    body +
    "\n}\n";
  fs.writeFileSync(filePath, content, "utf8");
}

function main() {
  const stamp = resolveStampArg();
  if (stamp) {
    syncBuildStamp(stamp);
  }

  const version = readAppVersion();
  syncPackageJson(version);
  syncPackageLock(version);
  syncReadme(version);
  syncLicense(version);
  syncMsiLicenseRtf(version);
  console.log(
    stamp
      ? `[sync-version] synced v${version}, build ${stamp}`
      : `[sync-version] synced v${version}`,
  );
}

main();
