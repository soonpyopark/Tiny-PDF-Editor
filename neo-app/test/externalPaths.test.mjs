import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';

// printService 는 electron app 에 의존하므로, 경로 유틸만 분리해 둔 동작을 여기서 재현한다.
function candidatePathsFromArgv(argv, cwd, skipPaths = []) {
  const skip = new Set(skipPaths.map((item) => path.resolve(item).toLowerCase()));
  const result = [];
  const seen = new Set();
  for (const raw of argv.slice(1)) {
    const arg = String(raw ?? '').trim();
    if (!arg || arg.startsWith('--') || (arg.startsWith('-') && arg.length <= 3)) continue;
    const full = path.resolve(cwd, arg);
    const key = full.toLowerCase();
    if (skip.has(key) || seen.has(key)) continue;
    seen.add(key);
    result.push(full);
  }
  return result;
}

function pathsFromArgv(argv, cwd, skipPaths = []) {
  return candidatePathsFromArgv(argv, cwd, skipPaths).filter((full) => {
    try {
      return fs.statSync(full).isFile();
    } catch {
      return false;
    }
  });
}

async function resolveExternalPaths(argv, cwd, options = {}, skipPaths = []) {
  const waitMs = Math.max(0, Number(options.waitMs) || 2000);
  const stepMs = Math.max(50, Number(options.stepMs) || 100);
  const existing = pathsFromArgv(argv, cwd, skipPaths);
  if (existing.length) return existing;
  const candidates = candidatePathsFromArgv(argv, cwd, skipPaths);
  if (!candidates.length || waitMs <= 0) return [];
  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, stepMs));
    const found = candidates.filter((full) => {
      try {
        return fs.statSync(full).isFile();
      } catch {
        return false;
      }
    });
    if (found.length) return found;
  }
  return [];
}

test('pathsFromArgv skips flags and keeps existing files', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'neo-ext-'));
  const file = path.join(dir, 'a.pdf');
  fs.writeFileSync(file, '%PDF');
  const found = pathsFromArgv(['app.exe', '--foo', file, '-v'], dir, ['app.exe']);
  assert.deepEqual(found, [file]);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('resolveExternalPaths waits for a late temp file', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'neo-ext-wait-'));
  const file = path.join(dir, 'late.pdf');
  const argv = ['app.exe', file];
  setTimeout(() => fs.writeFileSync(file, '%PDF'), 250);
  const found = await resolveExternalPaths(argv, dir, { waitMs: 1500, stepMs: 50 }, ['app.exe']);
  assert.deepEqual(found, [file]);
  fs.rmSync(dir, { recursive: true, force: true });
});

// silence unused import in some runners
void pathToFileURL;
