import crypto from 'node:crypto';
import { statePath } from './context.js';
import { readJsonSync, writeJsonSync } from './jsonStore.js';
import { recordLoginAudit } from './auditService.js';
import { normalizeClientIp } from './ipAllowlist.js';
import { getMemberById, verifyCredentials } from './membersService.js';
import { getSettings } from './settingsService.js';

const SESSIONS_FILE = 'sessions.json';
const SESSION_TTL_MS = 24 * 60 * 60 * 1000;
const REMEMBER_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const LOCKOUT_MAX_FAILURES = 3;
const LOCKOUT_MS = 5 * 60 * 1000;

/**
 * @typedef {{ memberId: string, createdAt: number, expiresAt: number, remember: boolean }} Session
 * @typedef {{ id: string, loginId: string, displayName: string, role: import('../shared/members.js').MemberRole }} SessionUser
 */

/** Live sessions keyed by raw token. @type {Map<string, Session>} */
const sessions = new Map();

/** Remembered sessions keyed by sha256(token) so the file holds no usable token. @type {Map<string, Session> | null} */
let remembered = null;

/** @param {string} token */
const hashToken = (token) => crypto.createHash('sha256').update(token).digest('hex');

function loadRemembered() {
  if (remembered) return remembered;
  remembered = new Map();
  const parsed = readJsonSync(statePath(SESSIONS_FILE), {});
  const now = Date.now();
  for (const [hash, value] of Object.entries(parsed?.sessions ?? {})) {
    if (value?.memberId && typeof value.expiresAt === 'number' && value.expiresAt > now) {
      remembered.set(hash, { ...value, remember: true });
    }
  }
  return remembered;
}

function saveRemembered() {
  if (!remembered) return;
  try {
    writeJsonSync(statePath(SESSIONS_FILE), {
      version: 1,
      sessions: Object.fromEntries(remembered),
    });
  } catch (err) {
    console.warn('[auth] failed to persist sessions:', err);
  }
}

/** @param {import('./membersService.js').MemberRecord} member @returns {SessionUser} */
function toSessionUser(member) {
  return {
    id: member.id,
    loginId: member.loginId,
    displayName: member.displayName,
    role: member.role,
  };
}

/**
 * Resolves a bearer token to its member. Role / active flag are read live, so
 * disabling or demoting a member takes effect on their next request.
 *
 * @param {string | null | undefined} token
 * @returns {SessionUser | null}
 */
export function getSessionUser(token) {
  if (!token || typeof token !== 'string') return null;

  let session = sessions.get(token) ?? null;
  if (!session) {
    const stored = loadRemembered().get(hashToken(token));
    if (stored) {
      session = stored;
      sessions.set(token, stored);
    }
  }
  if (!session) return null;

  if (session.expiresAt <= Date.now()) {
    revokeSession(token);
    return null;
  }

  const member = getMemberById(session.memberId);
  if (!member || !member.active) {
    revokeSession(token);
    return null;
  }
  return toSessionUser(member);
}

/** @param {string | null | undefined} token */
export function revokeSession(token) {
  if (!token || typeof token !== 'string') return;
  sessions.delete(token);
  if (loadRemembered().delete(hashToken(token))) saveRemembered();
}

/** Drops every session of a member (deleted / password reset). @param {string} memberId */
export function revokeMemberSessions(memberId) {
  for (const [token, session] of sessions) {
    if (session.memberId === memberId) sessions.delete(token);
  }
  let changed = false;
  for (const [hash, session] of loadRemembered()) {
    if (session.memberId === memberId) {
      remembered?.delete(hash);
      changed = true;
    }
  }
  if (changed) saveRemembered();
}

/**
 * @param {string} memberId
 * @param {boolean} remember
 */
function createSession(memberId, remember) {
  const token = crypto.randomBytes(24).toString('hex');
  const now = Date.now();
  /** @type {Session} */
  const session = {
    memberId,
    createdAt: now,
    expiresAt: now + (remember ? REMEMBER_TTL_MS : SESSION_TTL_MS),
    remember,
  };
  sessions.set(token, session);
  if (remember) {
    loadRemembered().set(hashToken(token), session);
    saveRemembered();
  }
  return token;
}

/* -------------------------------------------------------------------------- */
/* login + lockout                                                            */
/* -------------------------------------------------------------------------- */

/** Failed-login counters (process memory only). @type {Map<string, { failCount: number, lockedUntil: number | null }>} */
const attempts = new Map();

/** @param {string} key */
function getAttemptState(key) {
  const state = attempts.get(key);
  if (!state) return null;
  if (state.lockedUntil && state.lockedUntil <= Date.now()) {
    attempts.delete(key);
    return null;
  }
  return state;
}

/**
 * @param {string} id
 * @param {string} password
 * @param {{ remember?: boolean, clientIp?: string }} [options]
 */
export async function login(id, password, { remember = false, clientIp = '' } = {}) {
  const loginId = String(id ?? '').trim();
  const ip = normalizeClientIp(clientIp) ?? clientIp;
  const key = `${loginId.toLowerCase()}|${ip}`;
  // This PC is exempt, otherwise someone on the LAN could lock the owner out.
  const enforceLockout =
    getSettings().loginLockoutEnabled && Boolean(loginId) && ip !== '127.0.0.1';

  if (enforceLockout) {
    const state = getAttemptState(key);
    if (state?.lockedUntil && state.lockedUntil > Date.now()) {
      void recordLoginAudit({ loginId, result: 'locked', ip });
      return lockedResult(state.lockedUntil);
    }
  }

  const member = verifyCredentials(loginId, password);
  if (member) {
    attempts.delete(key);
    const token = createSession(member.id, Boolean(remember));
    void recordLoginAudit({ loginId: member.loginId, result: 'success', ip });
    return { success: true, token, user: toSessionUser(member) };
  }

  if (enforceLockout) {
    const state = getAttemptState(key) ?? { failCount: 0, lockedUntil: null };
    state.failCount += 1;
    if (state.failCount >= LOCKOUT_MAX_FAILURES) state.lockedUntil = Date.now() + LOCKOUT_MS;
    attempts.set(key, state);
    if (state.lockedUntil) {
      void recordLoginAudit({ loginId, result: 'locked', ip });
      return lockedResult(state.lockedUntil);
    }
  }

  void recordLoginAudit({ loginId: loginId || '(empty)', result: 'fail', ip });
  return { success: false };
}

/** @param {number} lockedUntil */
function lockedResult(lockedUntil) {
  return {
    success: false,
    locked: true,
    retryAfterSec: Math.max(1, Math.ceil((lockedUntil - Date.now()) / 1000)),
  };
}
