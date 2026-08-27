#!/usr/bin/env node
/**
 * Upgrade packages used by `npm run build:release`.
 *
 * Runtime: requirements.txt (PyMuPDF, PyQt6, openpyxl, ko-pii)
 * Build:   pyinstaller, pyinstaller-hooks-contrib, pillow, numpy
 * Node:    npm install + npm update (this project has no runtime npm deps)
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const REQUIREMENTS_PATH = path.join(root, "requirements.txt");

/** Packages used by build scripts but not listed in requirements.txt. */
export const EXTRA_PYTHON_PACKAGES = [
  "pyinstaller",
  "pyinstaller-hooks-contrib",
  "pillow",
  "numpy",
];

/**
 * @param {string} label
 * @param {string} command
 * @param {string[]} args
 */
function run(label, command, args) {
  console.log(`[release-deps] ${label}…`);
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    throw new Error(`${label} failed (exit ${result.status ?? 1})`);
  }
}

export function readRequirementNames() {
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

export function getInstalledVersion(packageName) {
  try {
    const output = spawnSync("python", ["-m", "pip", "show", packageName], {
      cwd: root,
      encoding: "utf8",
      shell: process.platform === "win32",
    });
    if (output.status !== 0) {
      return null;
    }
    const match = String(output.stdout || "").match(/^Version:\s*(.+)$/m);
    return match ? match[1].trim() : null;
  } catch {
    return null;
  }
}

export function releasePythonPackages() {
  return [...new Set([...readRequirementNames(), ...EXTRA_PYTHON_PACKAGES])];
}

export function syncRequirementsFile() {
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
  console.log(
    `[release-deps] refreshed ${path.relative(root, REQUIREMENTS_PATH)}`,
  );
}

export function printInstalledVersions(packages) {
  console.log("[release-deps] installed Python versions:");
  for (const name of packages) {
    const version = getInstalledVersion(name);
    if (version) {
      console.log(`  - ${name} ${version}`);
    }
  }
}

/**
 * @param {{ force?: boolean }} [opts]
 */
export function updateNpmStack(opts = {}) {
  if (opts.force) {
    run("npm install --force", "npm", ["install", "--force"]);
  } else {
    run("npm install", "npm", ["install"]);
  }
  run("npm update", "npm", ["update"]);
}

export function updatePythonStack() {
  run("upgrade pip", "python", ["-m", "pip", "install", "--upgrade", "pip"]);

  const packages = releasePythonPackages();
  if (packages.length === 0) {
    throw new Error("No Python packages found to upgrade.");
  }

  run("upgrade Python release packages", "python", [
    "-m",
    "pip",
    "install",
    "--upgrade",
    ...packages,
  ]);

  syncRequirementsFile();
  printInstalledVersions(packages);
}

/**
 * @param {{ skipNpm?: boolean, skipPython?: boolean, force?: boolean }} [opts]
 */
export async function upgradeReleaseDeps(opts = {}) {
  console.log("[release-deps] ===== started =====");
  if (!opts.skipNpm) {
    updateNpmStack(opts);
  }
  if (!opts.skipPython) {
    updatePythonStack();
  }
  console.log("[release-deps] ===== finished =====");
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  upgradeReleaseDeps({
    skipNpm: process.argv.includes("--skip-npm"),
    skipPython: process.argv.includes("--skip-python"),
    force: process.argv.includes("--force"),
  }).catch((error) => {
    console.error(
      "[release-deps] ERROR:",
      error instanceof Error ? error.message : error,
    );
    process.exit(1);
  });
}
