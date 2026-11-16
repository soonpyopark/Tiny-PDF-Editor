#!/usr/bin/env node
/**
 * Writes APP_BUILD_STAMP (YYMMDD_HHMMSS) into shared/constants.js so the
 * running app reports the same stamp that is in the artifact file names.
 *
 *   node scripts/sync-build-stamp.mjs [--stamp=261029_153000]
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const constantsPath = path.resolve(__dirname, '..', 'shared', 'constants.js');

const pad = (value) => String(value).padStart(2, '0');

export function formatBuildTimestamp(date = new Date()) {
  return `${String(date.getFullYear()).slice(-2)}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(
    date.getHours(),
  )}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

/** @param {string} stamp */
export function writeBuildStamp(stamp) {
  if (!/^\d{6}_\d{6}$/.test(stamp)) throw new Error(`Invalid build stamp: ${stamp}`);
  const source = fs.readFileSync(constantsPath, 'utf8');
  const next = source.replace(
    /(export const APP_BUILD_STAMP = )'[^']*'/,
    `$1'${stamp}'`,
  );
  if (next === source && !source.includes(`'${stamp}'`)) {
    throw new Error('APP_BUILD_STAMP not found in shared/constants.js');
  }
  fs.writeFileSync(constantsPath, next, 'utf8');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const arg = process.argv.find((item) => item.startsWith('--stamp='));
  const stamp = arg ? arg.slice('--stamp='.length) : formatBuildTimestamp();
  writeBuildStamp(stamp);
  console.log(`[stamp] APP_BUILD_STAMP=${stamp}`);
}
