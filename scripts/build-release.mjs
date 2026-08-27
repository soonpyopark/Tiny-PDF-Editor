#!/usr/bin/env node
/**
 * Build MSI + portable zip from one PyInstaller publish, one APP_BUILD_STAMP.
 *
 * First upgrades release-related npm/Python packages unless --skip-upgrade.
 *
 * Output (same YYMMDD_HHMMSS):
 *   msi/Tiny PDF Editor v{version}_{stamp}.msi
 *   msi/Tiny PDF Editor v{version}_{stamp}_portable.zip
 */

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildPortableApp, ensurePythonDeps } from "./build-dist.mjs";
import { upgradeReleaseDeps } from "./upgrade-release-deps.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const PUBLISH_EXE = path.join(
  ROOT,
  ".build",
  "pyinstaller-dist",
  "PDFEditor",
  "PDFEditor.exe",
);

function log(msg) {
  console.log(`[release] ${msg}`);
}

function run(cmd, options = {}) {
  log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", cwd: ROOT, shell: true, ...options });
}

function formatTimestamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  const yy = String(date.getFullYear()).slice(2);
  return `${yy}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

async function main() {
  const skipUpgrade = process.argv.includes("--skip-upgrade");
  if (!skipUpgrade) {
    log("upgrade release-related packages (npm + Python)");
    await upgradeReleaseDeps();
  } else {
    log("skip package upgrade (--skip-upgrade)");
  }

  const stamp = formatTimestamp();
  log(`build stamp: ${stamp}`);

  run(`node scripts/sync-version.mjs --stamp=${stamp}`);
  ensurePythonDeps();
  buildPortableApp();

  if (!fs.existsSync(PUBLISH_EXE)) {
    throw new Error(`Publish output not found: ${PUBLISH_EXE}`);
  }

  const env = {
    ...process.env,
    TINY_BUILD_STAMP: stamp,
    TINY_SKIP_STAMP: "1",
    TINY_SKIP_PUBLISH: "1",
  };

  run("node scripts/build-msi.mjs", { env });
  run("node scripts/build-portable.mjs", { env });

  log(`done — MSI + portable share stamp ${stamp}`);
}

main().catch((error) => {
  console.error("[release] failed:", error.message ?? error);
  process.exit(1);
});
