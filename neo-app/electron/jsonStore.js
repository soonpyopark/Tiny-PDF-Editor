import fs from 'node:fs';
import path from 'node:path';

/** Per-file promise chain so concurrent writers never interleave. @type {Map<string, Promise<unknown>>} */
const queues = new Map();

/**
 * @template T
 * @param {string} file
 * @param {T} fallback
 * @returns {T}
 */
export function readJsonSync(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

/**
 * Atomic write (tmp file + rename). Safe against crashes mid-write.
 * @param {string} file
 * @param {unknown} data
 */
export function writeJsonSync(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
  fs.renameSync(tmp, file);
}

/**
 * Serialises read-modify-write cycles on one file.
 *
 * @template T
 * @param {string} file
 * @param {() => Promise<T> | T} task
 * @returns {Promise<T>}
 */
export function withFileLock(file, task) {
  const previous = queues.get(file) ?? Promise.resolve();
  const next = previous.then(task, task);
  queues.set(
    file,
    next.catch(() => undefined),
  );
  return next;
}
