import crypto from 'node:crypto';
import { DEFAULT_ADMIN_ID, DEFAULT_ADMIN_PW } from '../shared/constants.js';
import {
  BOOTSTRAP_ADMIN_MEMBER_ID,
  LOGIN_ID_PATTERN,
  MIN_PASSWORD_LENGTH,
  normalizeMemberRole,
} from '../shared/members.js';
import { statePath } from './context.js';
import { readJsonSync, withFileLock, writeJsonSync } from './jsonStore.js';

const MEMBERS_FILE = 'members.json';

/**
 * @typedef {{
 *   id: string,
 *   loginId: string,
 *   displayName: string,
 *   passwordHash: string,
 *   role: import('../shared/members.js').MemberRole,
 *   active: boolean,
 *   createdAt: number,
 * }} MemberRecord
 */

/* -------------------------------------------------------------------------- */
/* password hashing (scrypt)                                                  */
/* -------------------------------------------------------------------------- */

const SCRYPT_PARAMS = { N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };
const KEY_LENGTH = 32;

/** @param {string} password */
export function hashPassword(password) {
  const salt = crypto.randomBytes(16);
  const hash = crypto.scryptSync(String(password), salt, KEY_LENGTH, SCRYPT_PARAMS);
  return `scrypt$${salt.toString('base64')}$${hash.toString('base64')}`;
}

/**
 * @param {string} password
 * @param {string} stored
 */
export function verifyPassword(password, stored) {
  const [scheme, saltB64, hashB64] = String(stored ?? '').split('$');
  if (scheme !== 'scrypt' || !saltB64 || !hashB64) return false;
  const expected = Buffer.from(hashB64, 'base64');
  const actual = crypto.scryptSync(
    String(password ?? ''),
    Buffer.from(saltB64, 'base64'),
    expected.length,
    SCRYPT_PARAMS,
  );
  return expected.length === actual.length && crypto.timingSafeEqual(expected, actual);
}

const DUMMY_HASH = hashPassword(crypto.randomBytes(8).toString('hex'));

/* -------------------------------------------------------------------------- */
/* storage                                                                    */
/* -------------------------------------------------------------------------- */

/** @type {MemberRecord[] | null} */
let cache = null;

function load() {
  if (!cache) {
    const parsed = readJsonSync(statePath(MEMBERS_FILE), { members: [] });
    cache = Array.isArray(parsed?.members) ? parsed.members : [];
  }
  return cache;
}

/**
 * Serialised read-modify-write. `mutate` receives a working copy and returns
 * the value for the caller; the copy is persisted afterwards.
 *
 * @template T
 * @param {(members: MemberRecord[]) => T} mutate
 * @returns {Promise<T>}
 */
function transact(mutate) {
  return withFileLock(statePath(MEMBERS_FILE), () => {
    const working = structuredClone(load());
    const result = mutate(working);
    writeJsonSync(statePath(MEMBERS_FILE), { version: 1, members: working });
    cache = working;
    return result;
  });
}

/** @param {MemberRecord} member */
export function toPublicMember(member) {
  return {
    id: member.id,
    loginId: member.loginId,
    displayName: member.displayName,
    role: member.role,
    active: member.active,
    isBootstrapAdmin: member.id === BOOTSTRAP_ADMIN_MEMBER_ID,
    createdAt: member.createdAt,
  };
}

/** Creates `admin / admin1234` when the members file has no bootstrap admin. */
export async function ensureBootstrapAdmin() {
  if (load().some((m) => m.id === BOOTSTRAP_ADMIN_MEMBER_ID)) return;
  await transact((members) => {
    members.unshift({
      id: BOOTSTRAP_ADMIN_MEMBER_ID,
      loginId: DEFAULT_ADMIN_ID,
      displayName: '관리자',
      passwordHash: hashPassword(DEFAULT_ADMIN_PW),
      role: 'super_admin',
      active: true,
      createdAt: Date.now(),
    });
  });
}

/* -------------------------------------------------------------------------- */
/* queries                                                                    */
/* -------------------------------------------------------------------------- */

export function listMembers() {
  return load().map(toPublicMember);
}

/** @param {string} id */
export function getMemberById(id) {
  return load().find((m) => m.id === id) ?? null;
}

/** @param {string} loginId */
export function getMemberByLoginId(loginId) {
  const key = String(loginId ?? '').trim().toLowerCase();
  if (!key) return null;
  return load().find((m) => m.loginId.toLowerCase() === key) ?? null;
}

/**
 * @param {string} loginId
 * @param {string} password
 * @returns {MemberRecord | null} the active member, or null on any mismatch
 */
export function verifyCredentials(loginId, password) {
  const member = getMemberByLoginId(loginId);
  // Always run one scrypt so unknown ids are not distinguishable by timing.
  const ok = verifyPassword(password, member?.passwordHash ?? DUMMY_HASH);
  return member && member.active && ok ? member : null;
}

/** True while the factory admin / admin1234 pair still works (login hint). */
export function isDefaultAdminPasswordActive() {
  const member = getMemberById(BOOTSTRAP_ADMIN_MEMBER_ID);
  return Boolean(member?.active && verifyPassword(DEFAULT_ADMIN_PW, member.passwordHash));
}

/* -------------------------------------------------------------------------- */
/* mutations                                                                  */
/* -------------------------------------------------------------------------- */

/** @param {string} password */
function assertPassword(password) {
  if (String(password ?? '').length < MIN_PASSWORD_LENGTH) {
    throw new Error(`비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`);
  }
}

/**
 * @param {{ loginId: string, displayName?: string, password: string, role?: string, active?: boolean }} input
 */
export function createMember(input) {
  const loginId = String(input?.loginId ?? '').trim();
  if (!LOGIN_ID_PATTERN.test(loginId)) {
    throw new Error('아이디는 영문·숫자·. _ - 조합 2~32자여야 합니다.');
  }
  assertPassword(input?.password);
  return transact((members) => {
    if (members.some((m) => m.loginId.toLowerCase() === loginId.toLowerCase())) {
      throw new Error('이미 사용 중인 아이디입니다.');
    }
    const member = {
      id: `member-${crypto.randomUUID()}`,
      loginId,
      displayName: String(input?.displayName ?? '').trim().slice(0, 40) || loginId,
      passwordHash: hashPassword(input.password),
      role: normalizeMemberRole(input?.role),
      active: input?.active !== false,
      createdAt: Date.now(),
    };
    members.push(member);
    return toPublicMember(member);
  });
}

/**
 * @param {string} id
 * @param {{ displayName?: string, role?: string, active?: boolean, password?: string }} patch
 */
export function updateMember(id, patch) {
  if (patch?.password) assertPassword(patch.password);
  return transact((members) => {
    const member = members.find((m) => m.id === id);
    if (!member) throw new Error('회원을 찾을 수 없습니다.');
    const bootstrap = member.id === BOOTSTRAP_ADMIN_MEMBER_ID;

    if (typeof patch.displayName === 'string') {
      member.displayName = patch.displayName.trim().slice(0, 40) || member.loginId;
    }
    if (patch.role !== undefined) {
      if (bootstrap && patch.role !== 'super_admin') {
        throw new Error('기본 관리자 계정의 권한은 변경할 수 없습니다.');
      }
      member.role = normalizeMemberRole(patch.role);
    }
    if (patch.active !== undefined) {
      if (bootstrap && patch.active === false) {
        throw new Error('기본 관리자 계정은 비활성화할 수 없습니다.');
      }
      member.active = Boolean(patch.active);
    }
    if (patch.password) member.passwordHash = hashPassword(patch.password);
    return toPublicMember(member);
  });
}

/** @param {string} id */
export function deleteMember(id) {
  return transact((members) => {
    if (id === BOOTSTRAP_ADMIN_MEMBER_ID) {
      throw new Error('기본 관리자 계정은 삭제할 수 없습니다.');
    }
    const index = members.findIndex((m) => m.id === id);
    if (index < 0) throw new Error('회원을 찾을 수 없습니다.');
    const [removed] = members.splice(index, 1);
    return toPublicMember(removed);
  });
}

/** Re-reads members.json after a backup restore replaced it on disk. */
export function reloadMembers() {
  cache = null;
}
