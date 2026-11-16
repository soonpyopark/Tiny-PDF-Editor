import { getAllowedIpCidrStrings, ipMatchesCidrRule, parseIPv4 } from '../shared/ipCidrCore.js';

/**
 * Normalises a socket address to dotted IPv4 (`::ffff:1.2.3.4` → `1.2.3.4`,
 * `::1` → `127.0.0.1`). Returns null for anything that is not IPv4.
 *
 * @param {string | null | undefined} ip
 * @returns {string | null}
 */
export function normalizeClientIp(ip) {
  if (!ip || typeof ip !== 'string') return null;
  let trimmed = ip.trim();
  if (trimmed.startsWith('::ffff:')) trimmed = trimmed.slice(7);
  if (trimmed === '::1') return '127.0.0.1';
  if (trimmed.includes(':')) return null;
  return parseIPv4(trimmed) !== null ? trimmed : null;
}

/**
 * Empty list = everyone. 127.0.0.1 (this PC) is always allowed.
 *
 * @param {string} clientIp
 * @param {unknown} allowedCidrs
 */
export function isIpAllowed(clientIp, allowedCidrs) {
  const rules = getAllowedIpCidrStrings(allowedCidrs);
  if (rules.length === 0) return true;

  const normalized = normalizeClientIp(clientIp);
  if (!normalized) return false;
  if (normalized === '127.0.0.1') return true;
  return rules.some((rule) => ipMatchesCidrRule(normalized, rule));
}

/**
 * The TCP peer address. Forwarding headers are deliberately ignored: this
 * server is reached directly, so a client-supplied X-Forwarded-For would let
 * anyone spoof an allowed IP.
 *
 * @param {import('node:http').IncomingMessage} req
 */
export function getClientIpFromRequest(req) {
  return normalizeClientIp(req.socket?.remoteAddress ?? '') ?? req.socket?.remoteAddress ?? '';
}

/** @param {string} value */
function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

/** @param {string} [clientIp] */
export function ipBlockedHtml(clientIp) {
  const shown = escapeHtml(clientIp || '알 수 없음');
  return `<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/><title>접속 제한</title>
<style>body{font-family:"Malgun Gothic",system-ui,sans-serif;margin:2rem;background:#eef2f7;color:#0f172a}
.box{max-width:28rem;margin:4rem auto;background:#fff;padding:1.75rem 2rem;border-radius:12px;box-shadow:0 8px 24px rgba(15,23,42,.08)}
h1{font-size:1.25rem;margin:0 0 .75rem}p{margin:.5rem 0;line-height:1.55;color:#475569}
code{font-size:.9em}</style></head>
<body><div class="box"><h1>접속이 허용되지 않은 IP입니다</h1>
<p>이 기기의 주소 <code>${shown}</code> 는 허용 목록에 없습니다.</p>
<p>환경설정 → 접근가능IP대역 에 이 주소 또는 대역을 등록하세요.</p>
<p>서버 PC에서는 <code>127.0.0.1</code> 로 접속할 수 있습니다.</p></div></body></html>`;
}
