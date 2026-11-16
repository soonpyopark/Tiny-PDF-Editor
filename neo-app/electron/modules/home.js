import { defineApi } from '../api/registry.js';
import { listMembers } from '../membersService.js';

/** Sample module: a read-only API the 홈 screen calls. Copy it for new features. */
export function register() {
  defineApi('home.summary', 'user', (_body, ctx) => ({
    serverTime: Date.now(),
    clientIp: ctx.clientIp,
    memberCount: listMembers().length,
  }));
}
