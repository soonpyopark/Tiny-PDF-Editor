import os from 'node:os';

/** Non-internal IPv4 addresses of this PC (LAN / VPN), for the access URL list. */
export function getLocalIPv4Addresses() {
  /** @type {string[]} */
  const result = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const info of list ?? []) {
      if (info.family === 'IPv4' && !info.internal) result.push(info.address);
    }
  }
  return result;
}
