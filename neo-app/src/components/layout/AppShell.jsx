import { useEffect, useState } from 'react';
import { useAppInfo } from '../../context/AppInfoContext.jsx';
import { useDialog } from '../../context/DialogContext.jsx';
import { FEATURES } from '../../features/registry.js';
import { useFullscreen } from '../../lib/fullscreen.js';
import { runStartupUpdateCheck } from '../../lib/updateCheckUi.js';
import SettingsView from '../settings/SettingsView.jsx';
import FullscreenExitButton from './FullscreenExitButton.jsx';
import TopBar from './TopBar.jsx';
import { EditorCommandsProvider } from '../../features/editor/editorCommands.jsx';

let startupChecked = false;

/** Top bar + the editor. No sidebar and no login. */
export default function AppShell() {
  const appInfo = useAppInfo();
  const dialog = useDialog();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const ActiveFeature = FEATURES[0]?.component;
  const fullscreen = useFullscreen();

  // Quiet update check once per page load (setting: 환경설정 → 일반).
  useEffect(() => {
    if (appInfo.startupUpdateCheck === false || startupChecked) return;
    startupChecked = true;
    void runStartupUpdateCheck(dialog);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <EditorCommandsProvider>
      <div className="flex h-full min-h-0 flex-col">
        {/* 전체화면에서는 메뉴바를 숨긴다. 언마운트하면 F11 등 단축키 핸들러도 사라지므로 CSS 로만 숨긴다. */}
        <div className={fullscreen ? 'hidden' : 'contents'}>
          <TopBar settingsOpen={settingsOpen} onToggleSettings={() => setSettingsOpen((open) => !open)} />
        </div>

        <main className="min-h-0 flex-1 bg-app-surface">
          {ActiveFeature ? <ActiveFeature /> : null}
        </main>

        {settingsOpen ? <SettingsView onClose={() => setSettingsOpen(false)} /> : null}
        <FullscreenExitButton />
      </div>
    </EditorCommandsProvider>
  );
}
