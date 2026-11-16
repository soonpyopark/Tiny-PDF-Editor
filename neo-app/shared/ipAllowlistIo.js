import { normalizeAllowedIpCidrs } from './ipCidrCore.js';

export const IP_ALLOWLIST_KIND = 'default-frame-ip-allowlist';
export const IP_ALLOWLIST_VERSION = 1;

/**
 * @param {{ cidr: string, description?: string }[]} allowedIpCidrs
 * @param {string} [exportedAt]
 */
export function buildIpAllowlistPayload(allowedIpCidrs, exportedAt = new Date().toISOString()) {
  return {
    kind: IP_ALLOWLIST_KIND,
    version: IP_ALLOWLIST_VERSION,
    exportedAt,
    allowedIpCidrs: normalizeAllowedIpCidrs(allowedIpCidrs),
  };
}

/**
 * @param {string} text
 * @returns {{ allowedIpCidrs: { cidr: string, description?: string }[] }}
 */
export function parseIpAllowlistPayload(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error('올바른 JSON 파일이 아닙니다.');
  }

  let list;
  if (Array.isArray(parsed)) {
    list = parsed;
  } else if (parsed && typeof parsed === 'object') {
    if (parsed.kind != null && !String(parsed.kind).endsWith('ip-allowlist')) {
      throw new Error('접근 가능 IP 대역 파일이 아닙니다.');
    }
    if (!('allowedIpCidrs' in parsed)) throw new Error('allowedIpCidrs 항목이 없습니다.');
    list = parsed.allowedIpCidrs;
  } else {
    throw new Error('IP 대역 파일 형식을 인식할 수 없습니다.');
  }

  const allowedIpCidrs = normalizeAllowedIpCidrs(list);
  if (Array.isArray(list) && list.length > 0 && allowedIpCidrs.length === 0) {
    throw new Error('유효한 허용 IP 항목이 없습니다.');
  }
  return { allowedIpCidrs };
}

/** @param {Date} [date] */
export function ipAllowlistExportFilename(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(
    date.getHours(),
  )}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
  return `default-frame-ip-allowlist-${stamp}.json`;
}
