#!/usr/bin/env node
/**
 * Upgrade all Python and Node dependencies used by Tiny PDF Editor.
 *
 * - Runtime: requirements.txt (PyMuPDF, PyQt6, openpyxl, ...)
 * - Build/branding: pyinstaller, pillow, numpy
 * - Node: npm update (when package-lock.json exists)
 *
 * After upgrading, requirements.txt minimum versions (>=) are refreshed
 * to match the installed versions.
 */

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const REQUIREMENTS_PATH = path.join(ROOT, "requirements.txt");

/** Packages used by build scripts but not listed in requirements.txt. */
const EXTRA_PYTHON_PACKAGES = ["pyinstaller", "pillow", "numpy"];

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

function log(msg) {
  console.log(`[update-all] ${msg}`);
}

function run(cmd, options = {}) {
  log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", cwd: ROOT, ...options });
}

function readRequirementNames() {
  if (!fs.existsSync(REQUIREMENTS_PATH)) {
    return [];
  }
  const names = [];
  for (const line of fs.readFileSync(REQUIREMENTS_PATH, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const match = trimmed.match(/^([A-Za-z0-9_.-]+)/);
    if (match) {
      names.push(match[1]);
    }
  }
  return names;
}

function getInstalledVersion(packageName) {
  try {
    const output = execSync(`python -m pip show ${packageName}`, {
      cwd: ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    const match = output.match(/^Version:\s*(.+)$/m);
    return match ? match[1].trim() : null;
  } catch {
    return null;
  }
}

function syncRequirementsFile() {
  if (!fs.existsSync(REQUIREMENTS_PATH)) {
    return;
  }
  const lines = fs.readFileSync(REQUIREMENTS_PATH, "utf8").split(/\r?\n/);
  const updated = lines.map((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      return line;
    }
    const match = trimmed.match(/^([A-Za-z0-9_.-]+)/);
    if (!match) {
      return line;
    }
    const name = match[1];
    const version = getInstalledVersion(name);
    if (!version) {
      return line;
    }
    return `${name}>=${version}`;
  });
  const text = updated.join("\n");
  fs.writeFileSync(
    REQUIREMENTS_PATH,
    text.endsWith("\n") ? text : `${text}\n`,
    "utf8",
  );
  log(`refreshed ${path.relative(ROOT, REQUIREMENTS_PATH)}`);
}

function printInstalledVersions(packages) {
  log("installed versions:");
  for (const name of packages) {
    const version = getInstalledVersion(name);
    if (version) {
      console.log(`  - ${name} ${version}`);
    }
  }
}

export function updateAllDependencies() {
  log("upgrading pip");
  run("python -m pip install --upgrade pip");

  const runtimePackages = readRequirementNames();
  const packages = [...new Set([...runtimePackages, ...EXTRA_PYTHON_PACKAGES])];
  if (packages.length === 0) {
    throw new Error("No Python packages found to upgrade.");
  }

  log("upgrading Python packages");
  run(`python -m pip install --upgrade ${packages.join(" ")}`);

  syncRequirementsFile();
  printInstalledVersions(packages);

  const lockPath = path.join(ROOT, "package-lock.json");
  if (fs.existsSync(lockPath)) {
    log("upgrading npm packages");
    run("npm update");
  } else {
    log("skipped npm update (no package-lock.json)");
  }

  log("done");
}

function main() {
  try {
    updateAllDependencies();
  } catch (error) {
    console.error("[update-all] failed:", error.message ?? error);
    process.exit(1);
  }
}

if (isMain) {
  main();
}
