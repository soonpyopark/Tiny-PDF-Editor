import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import { api } from './lib/apiClient.js';
import { AppInfoProvider } from './context/AppInfoContext.jsx';
import { DialogProvider } from './context/DialogContext.jsx';
import { applyAccentColor } from './lib/theme.js';
import './styles/index.css';

const root = ReactDOM.createRoot(document.getElementById('root'));

function renderStatus(message) {
  root.render(
    <div className="flex h-full w-full items-center justify-center bg-[#0a1a33] px-6 text-sm text-[#8fa0b8]">
      {message}
    </div>,
  );
}

renderStatus('연결 중…');

api('app.info')
  .then((appInfo) => {
    applyAccentColor(appInfo.accentColor);
    // 창 제목: 앱 이름 오른쪽에 버전 표시 (예: Tiny PDF Editor - NEO v1.0.0.0)
    document.title = `${appInfo.name} v${appInfo.version}`;
    root.render(
      <React.StrictMode>
        <AppInfoProvider value={appInfo}>
          <DialogProvider>
            <App />
          </DialogProvider>
        </AppInfoProvider>
      </React.StrictMode>,
    );
  })
  .catch((error) => {
    renderStatus(error instanceof Error ? error.message : '서버에 연결할 수 없습니다.');
  });
