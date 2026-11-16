import { useEffect, useState } from 'react';
import GeneralSettingsPanel from './GeneralSettingsPanel.jsx';

/**
 * 환경설정 탭. 로컬 전용이라 일반만 둡니다.
 * @type {{ id: string, label: string, component: import('react').ComponentType }[]}
 */
const SETTINGS_TABS = [{ id: 'general', label: '일반', component: GeneralSettingsPanel }];

/** @param {{ onClose: () => void }} props */
export default function SettingsView({ onClose }) {
  const [activeTab, setActiveTab] = useState('general');
  const ActivePanel = SETTINGS_TABS.find((tab) => tab.id === activeTab)?.component ?? GeneralSettingsPanel;

  useEffect(() => {
    const onKeyDown = (event) => {
      // Dialogs (z-2000/1100) get Escape first; only close when nothing is above us.
      if (event.key === 'Escape' && !document.querySelector('[role="dialog"], [role="alertdialog"]')) {
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[900] flex items-stretch justify-center bg-[rgba(32,33,36,0.45)] p-4 sm:p-6">
      <div
        className="flex min-h-0 w-full max-w-6xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        role="region"
        aria-label="환경설정"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="m-0 text-base font-semibold text-slate-900">환경설정</h2>
          <button
            type="button"
            className="inline-flex h-8 w-8 items-center justify-center rounded-full border-0 bg-transparent text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
            aria-label="환경설정 닫기"
            onClick={onClose}
          >
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path
                fill="currentColor"
                d="M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6 6.4 5Z"
              />
            </svg>
          </button>
        </div>

        {SETTINGS_TABS.length > 1 ? (
          <div className="border-b border-slate-200 px-4 pt-2">
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="환경설정 항목">
              {SETTINGS_TABS.map((tab) => {
                const selected = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    className={`-mb-px rounded-t-md px-4 py-2.5 text-sm transition-colors ${
                      selected
                        ? 'border border-b-white border-slate-200 bg-white font-semibold text-slate-900'
                        : 'border border-transparent font-medium text-slate-500 hover:text-slate-800'
                    }`}
                    onClick={() => setActiveTab(tab.id)}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-auto bg-slate-50/60 p-6" role="tabpanel">
          <ActivePanel key={activeTab} />
        </div>
      </div>
    </div>
  );
}
