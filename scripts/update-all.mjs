#!/usr/bin/env node
/**
 * Tiny PDF Editor — update deps (and optionally rebuild MSI).
 * Mirrors NAS4USB / My Desktop Calendar scripts/update-all.mjs
 * (Python + npm stack; no editor-core stacks).
 *
 * Options:
 *   --skip-git
 *   --skip-npm
 *   --skip-python
 *   --build          run npm run build:dist:msi
 *   --force          npm install --force; clear .build caches
 *   --skip-cores     accepted for NAS4USB bat compatibility (no-op)
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const REQUIREMENTS_PATH = path.join(root, "requirements.txt");

/** Packages used by build scripts but not listed in requirements.txt. */
const EXTRA_PYTHON_PACKAGES = ["pyinstaller", "pillow", "numpy"];

/**
 * @param {string[]} argv
 */
function parseArgs(argv) {
  return {
    skipGit: argv.includes("--skip-git"),
    skipNpm: argv.includes("--skip-npm"),
    skipPython: argv.includes("--skip-python"),
    skipCores: argv.includes("--skip-cores"),
    build: argv.includes("--build"),
    force: argv.includes("--force"),
  };
}

/**
 * @param {string} label
 * @param {string} command
 * @param {string[]} args
 */
function run(label, command, args) {
  console.log(`[update-all] ${label}…`);
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    throw new Error(`${label} failed (exit ${result.status ?? 1})`);
  }
}

async function clearForcedCaches() {
  const targets = [
    path.join(root, ".build", "pyinstaller-dist"),
    path.join(root, ".build", "pyinstaller-work"),
    path.join(root, "node_modules", ".cache"),
  ];
  for (const target of targets) {
    try {
      await fsp.rm(target, { recursive: true, force: true });
      console.log(`[update-all] cleared ${path.relative(root, target)} (force)`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.warn(`[update-all] could not clear ${target}: ${message}`);
    }
  }
}

async function gitPull() {
  try {
    await fsp.access(path.join(root, ".git"));
  } catch {
    console.log("[update-all] Not a git repo; skip git pull");
    return;
  }

  const status = spawnSync("git", ["status", "--porcelain"], {
    cwd: root,
    encoding: "utf8",
  });
  if (status.stdout?.trim()) {
    console.log("[update-all] Git working tree has local changes; skip git pull");
    return;
  }

  run("git pull", "git", ["pull", "--ff-only"]);
}

/**
 * @param {ReturnType<typeof parseArgs>} opts
 */
async function updateNpmStack(opts) {
  if (opts.force) {
    await clearForcedCaches();
    run("npm install --force", "npm", ["install", "--force"]);
  } else {
    run("npm install", "npm", ["install"]);
  }
  run("npm update", "npm", ["update"]);
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
  console.log(
    `[update-all] refreshed ${path.relative(root, REQUIREMENTS_PATH)}`,
  );
}

function printInstalledVersions(packages) {
  console.log("[update-all] installed Python versions:");
  for (const name of packages) {
    const version = getInstalledVersion(name);
    if (version) {
      console.log(`  - ${name} ${version}`);
    }
  }
}

function updatePythonStack() {
  run("upgrade pip", "python", ["-m", "pip", "install", "--upgrade", "pip"]);

  const runtimePackages = readRequirementNames();
  const packages = [...new Set([...runtimePackages, ...EXTRA_PYTHON_PACKAGES])];
  if (packages.length === 0) {
    throw new Error("No Python packages found to upgrade.");
  }

  run("upgrade Python packages", "python", [
    "-m",
    "pip",
    "install",
    "--upgrade",
    ...packages,
  ]);

  syncRequirementsFile();
  printInstalledVersions(packages);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));

  console.log("[update-all] ===== started =====");
  console.log(`[update-all] Project root: ${root}`);

  if (!opts.skipGit) {
    await gitPull();
  }

  if (!opts.skipNpm) {
    await updateNpmStack(opts);
  }

  if (!opts.skipPython) {
    updatePythonStack();
  }

  if (opts.skipCores) {
    console.log(
      "[update-all] --skip-cores: no editor cores in this project (ignored)",
    );
  }

  run("sync-version", "npm", ["run", "sync-version"]);

  const brandingScript = path.join(root, "scripts", "prepare-branding.py");
  if (fs.existsSync(brandingScript)) {
    try {
      run("prepare branding", "python", ["scripts/prepare-branding.py"]);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.warn(`[update-all] prepare branding skipped: ${message}`);
    }
  }

  if (opts.build) {
    run("build dist msi", "npm", ["run", "build:dist:msi"]);
  }

  console.log("[update-all] ===== finished =====");
}

main().catch((error) => {
  console.error(
    "[update-all] ERROR:",
    error instanceof Error ? error.message : error,
  );
  process.exit(1);
});
