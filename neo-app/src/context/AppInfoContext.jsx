import { createContext, useContext } from 'react';

/**
 * Public app info (`app.info`), fetched once before the first render.
 *
 * @typedef {{
 *   name: string,
 *   fileName: string,
 *   version: string,
 *   buildStamp: string,
 *   buildStampLabel: string,
 *   updateConfigured: boolean,
 *   accentColor: string,
 * }} AppInfo
 */

const AppInfoContext = createContext(/** @type {AppInfo | null} */ (null));

export const AppInfoProvider = AppInfoContext.Provider;

export function useAppInfo() {
  const info = useContext(AppInfoContext);
  if (!info) throw new Error('useAppInfo must be used within AppInfoProvider');
  return info;
}
