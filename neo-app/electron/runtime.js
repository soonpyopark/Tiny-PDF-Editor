/**
 * Late-bound handles that main.js fills in at startup, so API modules can use
 * the HTTP server / OS integration without importing Electron themselves.
 *
 * @typedef {{
 *   server: ReturnType<typeof import('./httpServer.js').createServerManager> | null,
 *   autoLaunch: {
 *     supported: boolean,
 *     get: () => boolean,
 *     set: (enabled: boolean) => void,
 *   } | null,
 *   syncTray: (() => void) | null,
 *   stateRoot: string,
 *   portable: boolean,
 * }} Runtime
 */

/** @type {Runtime} */
export const runtime = {
  server: null,
  autoLaunch: null,
  syncTray: null,
  stateRoot: '',
  portable: false,
};
