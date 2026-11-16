import { useEffect, useState } from 'react';
import { useAppInfo } from '../../context/AppInfoContext.jsx';
import { useDialog } from '../../context/DialogContext.jsx';
import { FEATURES } from '../../features/registry.js';
import { runStartupUpdateCheck } from '../../lib/updateCheckUi.js';
import SettingsView from '../settings/SettingsView.jsx';
import TopBar from './TopBar.jsx';
import { EditorCommandsProvider } from '../../features/editor/editorCommands.jsx';

let startupChecked = false;

/** Top bar + the editor. No sidebar and no login. */
export default function AppShell() {
  const appInfo = useAppInfo();
  const dialog = useDialog();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const ActiveFeature = FEATURES[0]?.component;

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
        <TopBar settingsOpen={settingsOpen} onToggleSettings={() => setSettingsOpen((open) => !open)} />

        <main className="min-h-0 flex-1 bg-app-surface">
          {ActiveFeature ? <ActiveFeature /> : null}
        </main>

        {settingsOpen ? <SettingsView onClose={() => setSettingsOpen(false)} /> : null}
      </div>
    </EditorCommandsProvider>
  );
}
