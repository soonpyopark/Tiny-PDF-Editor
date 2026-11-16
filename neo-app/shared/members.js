/**
 * @typedef {'member' | 'super_admin'} MemberRole
 *
 * @typedef {{
 *   id: string,
 *   loginId: string,
 *   displayName: string,
 *   role: MemberRole,
 *   active: boolean,
 *   isBootstrapAdmin: boolean,
 *   createdAt: number,
 * }} PublicMember
 */

export const MEMBER_ROLES = /** @type {const} */ (['member', 'super_admin']);

/** Fixed id of the seeded admin row (cannot be deleted / demoted / disabled). */
export const BOOTSTRAP_ADMIN_MEMBER_ID = 'member-bootstrap-admin';

export const LOGIN_ID_PATTERN = /^[A-Za-z0-9._-]{2,32}$/;
export const MIN_PASSWORD_LENGTH = 4;

/** @param {unknown} value */
export function normalizeMemberRole(value) {
  return value === 'super_admin' ? 'super_admin' : 'member';
}

/** @param {MemberRole | string | undefined} role */
export function memberRoleToLabel(role) {
  return role === 'super_admin' ? '총괄관리자' : '일반사용자';
}
