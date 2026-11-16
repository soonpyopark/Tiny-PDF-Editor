import { useState } from 'react';
import { ACCENT_COLOR_PRESETS, normalizeAccentColor } from '../../../shared/theme.js';
import { api, getNative } from '../../lib/apiClient.js';
import { useAppInfo } from '../../context/AppInfoContext.jsx';
import { useDialog } from '../../context/DialogContext.jsx';
import { useLoad } from '../../hooks/useLoad.js';
import { applyAccentColor } from '../../lib/theme.js';
import { Badge, LoadError, Loading, Section, ToggleRow, btnClass, codeClass } from './ui.jsx';

export default function GeneralSettingsPanel() {
  const appInfo = useAppInfo();
  const dialog = useDialog();
  const native = getNative();
  const { data: settings, loading, error, reload, setData } = useLoad(() => api('settings.get'));
  const { data: server } = useLoad(() => api('server.info'));
  const [customColor, setCustomColor] = useState('');

  if (loading && !settings) return <Loading />;
  if (error || !settings) return <LoadError message={error} onRetry={reload} />;

  /** @param {Record<string, unknown>} patch */
  const save = async (patch) => {
    try {
      setData(await api('settings.update', patch));
    } catch (err) {
      void dialog.alert({
        title: '환경설정',
        body: err instanceof Error ? err.message : '설정 저장에 실패했습니다.',
      });
      void reload();
    }
  };

  const pickAccent = (color) => {
    const accent = normalizeAccentColor(color, settings.accentColor);
    applyAccentColor(accent);
    void save({ accentColor: accent });
  };

  const runtimeLabel = server?.isDev ? '개발 모드' : server?.portable ? '포터블' : '설치형';

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Section title="프로그램 정보">
        <dl className="grid grid-cols-[110px_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-slate-500">이름</dt>
          <dd className="m-0 text-slate-800">{appInfo.name}</dd>
          <dt className="text-slate-500">버전</dt>
          <dd className="m-0 text-slate-800">
            v{appInfo.version} <span className="text-slate-400">· 빌드 {appInfo.buildStampLabel}</span>
          </dd>
          <dt className="text-slate-500">실행 형태</dt>
          <dd className="m-0">
            <Badge tone="slate">{runtimeLabel}</Badge>
          </dd>
          <dt className="text-slate-500">데이터 폴더</dt>
          <dd className="m-0 flex flex-wrap items-center gap-2">
            <code className={`${codeClass} break-all`}>{server?.stateRoot ?? '…'}</code>
            {native?.openStateFolder ? (
              <button type="button" className={btnClass} onClick={() => void native.openStateFolder('')}>
                폴더 열기
              </button>
            ) : null}
          </dd>
        </dl>
      </Section>

      <Section title="테마 색상" description="버튼·강조 색을 바꿉니다.">
        <div className="flex flex-wrap items-center gap-2">
          {ACCENT_COLOR_PRESETS.map((color) => {
            const selected = color === settings.accentColor;
            return (
              <button
                key={color}
                type="button"
                title={color}
                aria-label={`테마 색상 ${color}`}
                aria-pressed={selected}
                className={`h-7 w-7 rounded-full border-2 transition-transform hover:scale-110 ${
                  selected ? 'border-slate-800' : 'border-white shadow ring-1 ring-slate-200'
                }`}
                style={{ backgroundColor: color }}
                onClick={() => pickAccent(color)}
              />
            );
          })}
          <label className="ml-2 inline-flex items-center gap-2 text-xs text-slate-500">
            직접 선택
            <input
              type="color"
              className="h-7 w-9 cursor-pointer rounded border border-slate-300 bg-white p-0.5"
              value={customColor || settings.accentColor}
              onChange={(event) => setCustomColor(event.target.value)}
              onBlur={() => customColor && pickAccent(customColor)}
            />
          </label>
        </div>
      </Section>

      <Section title="시작">
        <div className="divide-y divide-slate-100">
          <ToggleRow
            label="시작 시 업데이트 확인"
            hint="프로그램을 열 때 새 버전이 있으면 알려 줍니다."
            checked={settings.startupUpdateCheck}
            onChange={(checked) => void save({ startupUpdateCheck: checked })}
          />
          <ToggleRow
            label="Windows / macOS 로그인 시 자동 실행"
            hint={
              settings.autoLaunchSupported
                ? 'OS 로그인 시 프로그램을 자동으로 시작합니다.'
                : '설치된 프로그램에서만 사용할 수 있습니다. (개발 모드에서는 비활성)'
            }
            checked={settings.autoLaunch}
            disabled={!settings.autoLaunchSupported}
            onChange={(checked) => void save({ autoLaunch: checked })}
          />
        </div>
      </Section>

      <Section title="종료">
        <div className="divide-y divide-slate-100">
          <ToggleRow
            label="창을 닫으면 트레이로 보내기"
            hint="켜 두면 창의 닫기(X) 버튼을 눌러도 프로그램이 트레이에서 계속 실행됩니다. 끄면 닫기(X)가 프로그램 종료가 됩니다. 트레이의 Exit 는 언제나 종료합니다."
            checked={settings.closeToTray !== false}
            onChange={(checked) => void save({ closeToTray: checked })}
          />
        </div>
      </Section>
    </div>
  );
}
