import { useState } from 'react';
import { useAppInfo } from '../../context/AppInfoContext.jsx';
import { useDialog } from '../../context/DialogContext.jsx';
import { getNative } from '../../lib/apiClient.js';
import { runUpdateCheck } from '../../lib/updateCheckUi.js';
import AppLogo from '../common/AppLogo.jsx';
import AppMenuBar from './AppMenuBar.jsx';

const iconBtnClass =
  'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-transparent text-slate-500 transition-colors hover:border-slate-200 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50';
const iconBtnActiveClass =
  'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-app-accentBorder bg-app-accentSoft text-app-accent transition-colors';

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        fill="currentColor"
        d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"
      />
    </svg>
  );
}

/** 원 안의 물음표 (정보). */
function AboutIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M9.4 9.3a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.2-2.6 3.9" />
      <circle cx="12" cy="17.1" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  );
}

function UpdateCheckIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 6V3L8 7l4 4V8c2.76 0 5 2.24 5 5a5 5 0 0 1-8.66 3.46l-1.42 1.42A7 7 0 0 0 19 13c0-3.87-3.13-7-7-7zm-5 .54A7 7 0 0 0 5 13c0 3.87 3.13 7 7 7v3l4-4-4-4v3c-2.76 0-5-2.24-5-5 0-1.16.4-2.23 1.07-3.08L7 8.54z"
      />
    </svg>
  );
}

/**
 * Top bar: Tiny PDF Editor menus, then 정보(?) · 업데이트 확인 · 환경설정.
 *
 * @param {{ settingsOpen: boolean, onToggleSettings: () => void }} props
 */
export default function TopBar({ settingsOpen, onToggleSettings }) {
  const dialog = useDialog();
  const appInfo = useAppInfo();
  const [updateChecking, setUpdateChecking] = useState(false);
  const handleUpdateCheck = () => {
    if (updateChecking) return;
    setUpdateChecking(true);
    void runUpdateCheck(dialog).finally(() => setUpdateChecking(false));
  };

  // Electron 창은 스플래시 형태의 정보 창을 쓰고, 브라우저(LAN 접속)는 기존 대화상자를 쓴다.
  const showAbout = () => {
    const native = getNative();
    if (native?.showAboutSplash) {
      void native.showAboutSplash();
      return;
    }
    void dialog.alert({
      title: appInfo.name,
      icon: <AppLogo size={72} />,
      body: `버전: v${appInfo.version}\n빌드: ${appInfo.buildStampLabel}\n라이선스: MIT License`,
    });
  };

  return (
    <header className="shrink-0 border-b border-app-border bg-white px-3 py-2 min-h-12">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex min-w-0 flex-1 items-center">
          <AppMenuBar />
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2">
          <button type="button" className={iconBtnClass} aria-label="정보" title="정보" data-top-about="1" onClick={showAbout}>
            <AboutIcon />
          </button>

          <button
            type="button"
            className={iconBtnClass}
            aria-label="업데이트 확인"
            title="업데이트 확인"
            disabled={updateChecking}
            onClick={handleUpdateCheck}
          >
            <UpdateCheckIcon />
          </button>

          <button
            type="button"
            className={settingsOpen ? iconBtnActiveClass : iconBtnClass}
            aria-label={settingsOpen ? '환경설정 닫기' : '환경설정'}
            title={settingsOpen ? '환경설정 닫기' : '환경설정'}
            aria-pressed={settingsOpen}
            onClick={onToggleSettings}
          >
            <SettingsIcon />
          </button>
        </div>
      </div>
    </header>
  );
}
