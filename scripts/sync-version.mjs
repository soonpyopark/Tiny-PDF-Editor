#!/usr/bin/env node
/**
 * Sync project version from pdf_editor/version.py into package.json, README, LICENSE.
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

function syncPackageJson(version) {
  const filePath = path.join(ROOT, "package.json");
  const data = JSON.parse(fs.readFileSync(filePath, "utf8"));
  data.version = version;
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

  fs.writeFileSync(filePath, text, "utf8");
}

function syncMsiLicenseRtf(version) {
  const filePath = path.join(ROOT, "msi", "License.rtf");
  if (!fs.existsSync(filePath)) {
    return;
  }
  let text = fs.readFileSync(filePath, "utf8");
  text = text.replace(
    /Tiny PDF Editor v[0-9][^\\]*\\par/,
    `Tiny PDF Editor v${version}\\par`,
  );
  fs.writeFileSync(filePath, text, "utf8");
}

function main() {
  const version = readAppVersion();
  syncPackageJson(version);
  syncReadme(version);
  syncLicense(version);
  syncMsiLicenseRtf(version);
  console.log(`[sync-version] synced v${version}`);
}

main();
