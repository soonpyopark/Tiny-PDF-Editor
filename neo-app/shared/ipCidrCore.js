/**
 * IPv4 / CIDR / range validation + matching (shared by browser and server).
 * Supported: single IP, CIDR (192.168.0.0/24), range (221.168.1.0-221.168.12.255)
 */

/**
 * @param {string} ip
 * @returns {number | null}
 */
export function parseIPv4(ip) {
  const parts = String(ip).split('.');
  if (parts.length !== 4) return null;
  const nums = parts.map((part) => (/^\d{1,3}$/.test(part) ? Number.parseInt(part, 10) : NaN));
  if (nums.some((n) => Number.isNaN(n) || n < 0 || n > 255)) return null;
  return ((nums[0] << 24) | (nums[1] << 16) | (nums[2] << 8) | nums[3]) >>> 0;
}

/** @param {string} entry */
function parseCidrPart(entry) {
  const trimmed = entry.trim();
  if (!trimmed) return null;

  if (!trimmed.includes('/')) {
    const ip = parseIPv4(trimmed);
    if (ip === null) return null;
    return { type: 'cidr', network: ip, mask: 0xffffffff };
  }

  const slash = trimmed.lastIndexOf('/');
  const ip = parseIPv4(trimmed.slice(0, slash).trim());
  const prefix = Number.parseInt(trimmed.slice(slash + 1).trim(), 10);
  if (ip === null || Number.isNaN(prefix) || prefix < 0 || prefix > 32) return null;

  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
  return { type: 'cidr', network: (ip & mask) >>> 0, mask };
}

/** @param {string} entry */
function parseIpRangePart(entry) {
  const trimmed = entry.trim();
  if (!trimmed.includes('-') || trimmed.includes('/')) return null;

  const dashIndex = trimmed.indexOf('-');
  const startPart = trimmed.slice(0, dashIndex).trim();
  const endPart = trimmed.slice(dashIndex + 1).trim();
  if (!startPart || !endPart || endPart.includes('-')) return null;

  const start = parseIPv4(startPart);
  const end = parseIPv4(endPart);
  if (start === null || end === null || start > end) return null;
  return { type: 'range', start, end };
}

/** @param {string} entry */
function parseIpRule(entry) {
  if (typeof entry !== 'string') return null;
  const trimmed = entry.trim();
  if (!trimmed) return null;
  if (trimmed.includes('/')) return parseCidrPart(trimmed);
  if (trimmed.includes('-')) return parseIpRangePart(trimmed);
  return parseCidrPart(trimmed);
}

/** @param {string} value */
export function isValidIpOrCidr(value) {
  return typeof value === 'string' && parseIpRule(value) !== null;
}

/**
 * @typedef {{ cidr: string, description?: string }} AllowedIpEntry
 */

/**
 * @param {unknown} list
 * @returns {AllowedIpEntry[]}
 */
export function normalizeAllowedIpCidrs(list) {
  if (!Array.isArray(list)) return [];
  const seen = new Set();
  /** @type {AllowedIpEntry[]} */
  const result = [];
  for (const item of list) {
    let cidr = '';
    let description = '';

    if (typeof item === 'string') {
      cidr = item.trim();
    } else if (item && typeof item === 'object' && typeof item.cidr === 'string') {
      cidr = item.cidr.trim();
      if (typeof item.description === 'string') description = item.description.trim();
    } else {
      continue;
    }

    if (!cidr || !isValidIpOrCidr(cidr)) continue;
    const key = cidr.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(description ? { cidr, description } : { cidr });
  }
  return result;
}

/**
 * @param {unknown} list
 * @returns {string[]}
 */
export function getAllowedIpCidrStrings(list) {
  return normalizeAllowedIpCidrs(list).map((entry) => entry.cidr);
}

/**
 * @param {string} ipString
 * @param {string} rule
 */
export function ipMatchesCidrRule(ipString, rule) {
  const ipNum = parseIPv4(ipString);
  if (ipNum === null) return false;
  const parsed = parseIpRule(rule);
  if (!parsed) return false;
  if (parsed.type === 'range') return ipNum >= parsed.start && ipNum <= parsed.end;
  return ((ipNum & parsed.mask) >>> 0) === parsed.network;
}
