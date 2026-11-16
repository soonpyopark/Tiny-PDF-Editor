import { useEffect, useRef, useState } from 'react';
import { api, apiDownload, getNative, saveBlob } from '../../lib/apiClient.js';
import { useDialog } from '../../context/DialogContext.jsx';
import { useLoad } from '../../hooks/useLoad.js';
import { formatBytes, formatDateTime, readFileAsBase64 } from '../../lib/format.js';
import {
  Badge,
  Field,
  LoadError,
  Loading,
  Section,
  ToggleRow,
  btnClass,
  btnDangerClass,
  btnPrimaryClass,
  codeClass,
  inputClass,
} from './ui.jsx';

const KIND_LABEL = { manual: '수동', auto: '자동', prerestore: '복원 전', imported: '가져옴' };
const KIND_TONE = { manual: 'default', auto: 'green', prerestore: 'amber', imported: 'slate' };
const INTERVALS = [
  { hours: 6, label: '6시간마다' },
  { hours: 12, label: '12시간마다' },
  { hours: 24, label: '매일' },
  { hours: 72, label: '3일마다' },
  { hours: 168, label: '매주' },
];

export default function BackupSettingsPanel() {
  const dialog = useDialog();
  const native = getNative();
  const { data, loading, error, reload } = useLoad(() => api('backup.status'));
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [intervalHours, setIntervalHours] = useState(24);
  const [keepCount, setKeepCount] = useState(10);
  const [busy, setBusy] = useState('');
  const importRef = useRef(/** @type {HTMLInputElement | null} */ (null));

  useEffect(() => {
    if (!data) return;
    setAutoEnabled(data.config.autoEnabled);
    setIntervalHours(data.config.intervalHours);
    setKeepCount(data.config.keepCount);
  }, [data]);

  if (loading && !data) return <Loading />;
  if (error || !data) return <LoadError message={error} onRetry={reload} />;

  const configDirty =
    autoEnabled !== data.config.autoEnabled ||
    intervalHours !== data.config.intervalHours ||
    keepCount !== data.config.keepCount;

  /**
   * @param {string} label
   * @param {() => Promise<unknown>} task
   * @param {string} [failTitle]
   */
  const run = async (label, task, failTitle = '백업 관리') => {
    setBusy(label);
    try {
      await task();
      return true;
    } catch (err) {
      void dialog.alert({ title: failTitle, body: err instanceof Error ? err.message : '실패했습니다.' });
      return false;
    } finally {
      setBusy('');
    }
  };

  const handleBackupNow = async () => {
    if (await run('backup', () => api('backup.run'))) {
      await reload();
    }
  };

  const handleSaveConfig = async () => {
    if (await run('config', () => api('backup.saveConfig', { autoEnabled, intervalHours, keepCount }))) {
      await reload();
    }
  };

  const handleDownload = (entry) =>
    void run('download', async () => {
      saveBlob(await apiDownload('backup.download', { fileName: entry.fileName }), entry.fileName);
    });

  const handleDelete = async (entry) => {
    const ok = await dialog.confirm({
      title: '백업 삭제',
      body: `「${entry.fileName}」을(를) 삭제할까요?`,
      confirmLabel: '삭제',
      confirmVariant: 'danger',
    });
    if (ok && (await run('delete', () => api('backup.delete', { fileName: entry.fileName })))) {
      await reload();
    }
  };

  const handleRestore = async (entry) => {
    const ok = await dialog.confirm({
      title: '백업 복원',
      body: `「${entry.fileName}」(${formatDateTime(entry.createdAt)}) 시점으로 복원할까요?\n\n설정·회원 등 현재 데이터가 백업 내용으로 덮어쓰기 됩니다.\n복원 직전 상태는 "복원 전" 백업으로 자동 보관됩니다.`,
      confirmLabel: '복원',
      confirmVariant: 'danger',
    });
    if (!ok) return;
    let restored = 0;
    if (
      await run('restore', async () => {
        restored = (await api('backup.restore', { fileName: entry.fileName })).restored;
      })
    ) {
      await dialog.alert({
        title: '백업 복원',
        body: `${restored}개 파일을 복원했습니다.\n서버 포트·접속 범위 설정은 프로그램을 다시 시작하면 반영됩니다.`,
      });
      window.location.reload();
    }
  };

  const handleImport = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (
      await run('import', async () => {
        await api('backup.import', { dataBase64: await readFileAsBase64(file) });
      }, '백업 가져오기')
    ) {
      await reload();
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <Section
        title="백업"
        description={
          <>
            데이터 폴더(<code className={`${codeClass} break-all`}>{data.stateRoot}</code>)의 설정·회원 등 모든 파일을
            zip 으로 보관합니다. 로그인 세션과 백업 파일 자체는 포함되지 않습니다.
          </>
        }
      >
        <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
          {native?.openStateFolder ? (
            <button type="button" className={btnClass} onClick={() => void native.openStateFolder('backups')}>
              백업 폴더 열기
            </button>
          ) : null}
          <button type="button" className={btnClass} disabled={Boolean(busy)} onClick={() => importRef.current?.click()}>
            백업 가져오기
          </button>
          <input
            ref={importRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={(event) => void handleImport(event)}
          />
          <button type="button" className={btnPrimaryClass} disabled={Boolean(busy)} onClick={() => void handleBackupNow()}>
            {busy === 'backup' ? '백업 중…' : '지금 백업'}
          </button>
        </div>

        {data.entries.length === 0 ? (
          <p className="m-0 rounded-lg border border-dashed border-slate-300 px-3 py-4 text-sm text-slate-500">
            아직 백업이 없습니다. [지금 백업]을 눌러 만들어 보세요.
          </p>
        ) : (
          <div className="overflow-auto rounded-md border border-slate-200">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-medium">파일</th>
                  <th className="px-3 py-2 font-medium">종류</th>
                  <th className="px-3 py-2 font-medium">크기</th>
                  <th className="px-3 py-2 font-medium">생성</th>
                  <th className="px-3 py-2 text-right font-medium">관리</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => (
                  <tr key={entry.fileName} className="border-t border-slate-100">
                    <td className="px-3 py-2 font-mono text-xs text-slate-700">{entry.fileName}</td>
                    <td className="px-3 py-2">
                      <Badge tone={KIND_TONE[entry.kind] ?? 'slate'}>{KIND_LABEL[entry.kind] ?? entry.kind}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-600">{formatBytes(entry.size)}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-500">{formatDateTime(entry.createdAt)}</td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-1.5">
                        <button type="button" className={btnClass} disabled={Boolean(busy)} onClick={() => handleDownload(entry)}>
                          다운로드
                        </button>
                        <button type="button" className={btnClass} disabled={Boolean(busy)} onClick={() => void handleRestore(entry)}>
                          복원
                        </button>
                        <button type="button" className={btnDangerClass} disabled={Boolean(busy)} onClick={() => void handleDelete(entry)}>
                          삭제
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="자동 백업" description="프로그램이 실행 중일 때 주기에 맞춰 백업합니다.">
        <ToggleRow
          label="자동 백업 사용"
          hint={
            data.config.lastRunAt
              ? `마지막 자동 백업: ${formatDateTime(data.config.lastRunAt)}`
              : '아직 자동 백업이 실행된 적이 없습니다.'
          }
          checked={autoEnabled}
          onChange={setAutoEnabled}
        />
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Field label="주기">
            <select
              className={inputClass}
              value={intervalHours}
              disabled={!autoEnabled}
              onChange={(event) => setIntervalHours(Number(event.target.value))}
            >
              {INTERVALS.map((item) => (
                <option key={item.hours} value={item.hours}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="자동 백업 보관 개수" hint="오래된 자동 백업부터 삭제됩니다. 수동 백업은 지우지 않습니다.">
            <input
              type="number"
              min={1}
              max={200}
              className={inputClass}
              value={keepCount}
              disabled={!autoEnabled}
              onChange={(event) => setKeepCount(Number(event.target.value) || 1)}
            />
          </Field>
        </div>
        <div className="mt-4">
          <button
            type="button"
            className={btnPrimaryClass}
            disabled={!configDirty || Boolean(busy)}
            onClick={() => void handleSaveConfig()}
          >
            {busy === 'config' ? '저장 중…' : '저장'}
          </button>
        </div>
      </Section>
    </div>
  );
}
