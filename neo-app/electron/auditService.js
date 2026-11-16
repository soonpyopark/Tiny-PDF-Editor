import crypto from 'node:crypto';
import { statePath } from './context.js';
import { readJsonSync, withFileLock, writeJsonSync } from './jsonStore.js';

const AUDIT_FILE = 'login-audit.json';
const MAX_ENTRIES = 500;

/**
 * @typedef {{
 *   id: string,
 *   at: number,
 *   loginId: string,
 *   result: 'success' | 'fail' | 'locked',
 *   ip: string,
 * }} LoginAuditEntry
 */

/**
 * @param {{ loginId: string, result: LoginAuditEntry['result'], ip?: string }} entry
 */
export function recordLoginAudit(entry) {
  return withFileLock(statePath(AUDIT_FILE), () => {
    const data = readJsonSync(statePath(AUDIT_FILE), { entries: [] });
    const entries = Array.isArray(data?.entries) ? data.entries : [];
    entries.push({
      id: crypto.randomUUID(),
      at: Date.now(),
      loginId: String(entry.loginId ?? '').slice(0, 64),
      result: entry.result,
      ip: String(entry.ip ?? ''),
    });
    writeJsonSync(statePath(AUDIT_FILE), { version: 1, entries: entries.slice(-MAX_ENTRIES) });
  }).catch((err) => console.warn('[audit] write failed:', err));
}

/** Newest first. @returns {LoginAuditEntry[]} */
export function listLoginAudit(limit = 200) {
  const data = readJsonSync(statePath(AUDIT_FILE), { entries: [] });
  const entries = Array.isArray(data?.entries) ? data.entries : [];
  return entries.slice(-limit).reverse();
}

export function clearLoginAudit() {
  return withFileLock(statePath(AUDIT_FILE), () => {
    writeJsonSync(statePath(AUDIT_FILE), { version: 1, entries: [] });
  });
}
