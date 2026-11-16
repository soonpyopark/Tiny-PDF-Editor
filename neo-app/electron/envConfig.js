import fs from 'node:fs';
import path from 'node:path';

/**
 * Minimal `.env` reader (KEY=VALUE, `#` comments). Values never override
 * real environment variables.
 *
 * @param {string} dir
 * @returns {Record<string, string>}
 */
export function readEnvFile(dir) {
  const file = path.join(dir, '.env');
  /** @type {Record<string, string>} */
  const result = {};
  let text = '';
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    return result;
  }
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    result[key] = value;
  }
  return result;
}

/**
 * @param {string[]} dirs folders to look for `.env` in (first match per key wins)
 * @returns {{ get: (key: string) => string | undefined }}
 */
export function createEnvReader(dirs) {
  const merged = {};
  for (const dir of [...dirs].reverse()) Object.assign(merged, readEnvFile(dir));
  return {
    get: (key) => process.env[key] ?? merged[key],
  };
}
