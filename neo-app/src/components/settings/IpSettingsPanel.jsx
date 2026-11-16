import { useEffect, useRef, useState } from 'react';
import { isValidIpOrCidr, normalizeAllowedIpCidrs } from '../../../shared/ipCidrCore.js';
import {
  buildIpAllowlistPayload,
  ipAllowlistExportFilename,
  parseIpAllowlistPayload,
} from '../../../shared/ipAllowlistIo.js';
import { api } from '../../lib/apiClient.js';
import { useAuth } from '../../context/AuthContext.jsx';
import { useDialog } from '../../context/DialogContext.jsx';
import { useLoad } from '../../hooks/useLoad.js';
import { downloadTextFile, readFileAsText } from '../../lib/format.js';
import {
  Field,
  LoadError,
  Loading,
  Section,
  btnClass,
  btnDangerClass,
  btnPrimaryClass,
  codeClass,
  inputClass,
} from './ui.jsx';

export default function IpSettingsPanel() {
  const dialog = useDialog();
  const { clientIp } = useAuth();
  const { data: settings, loading, error, reload } = useLoad(() => api('settings.get'));
  const [list, setList] = useState(/** @type {import('../../../shared/ipCidrCore.js').AllowedIpEntry[]} */ ([]));
  const [cidrDraft, setCidrDraft] = useState('');
  const [descriptionDraft, setDescriptionDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const importRef = useRef(/** @type {HTMLInputElement | null} */ (null));
  const saveTimerRef = useRef(/** @type {ReturnType<typeof setTimeout> | null} */ (null));

  useEffect(() => {
    if (settings) setList(normalizeAllowedIpCidrs(settings.allowedIpCidrs));
  }, [settings]);

  useEffect(
    () => () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    },
    [],
  );

  if (loading && !settings) return <Loading />;
  if (error || !settings) return <LoadError message={error} onRetry={reload} />;

  /**
   * @param {import('../../../shared/ipCidrCore.js').AllowedIpEntry[]} next
   * @returns {Promise<boolean>}
   */
  const persist = async (next) => {
    setSaving(true);
    try {
      const result = await api('ip.set', { allowedIpCidrs: next });
      setList(result.allowedIpCidrs);
      return true;
    } catch (err) {
      void dialog.alert({
        title: '접근 가능 IP 대역',
        body: err instanceof Error ? err.message : '저장하지 못했습니다.',
      });
      await reload();
      return false;
    } finally {
      setSaving(false);
    }
  };

  const addEntry = async () => {
    const value = cidrDraft.trim();
    if (!value) {
      void dialog.alert({ title: '접근 가능 IP 대역', body: '허용 IP 주소를 입력해 주세요.' });
      return;
    }
    if (!isValidIpOrCidr(value)) {
      void dialog.alert({
        title: '접근 가능 IP 대역',
        body: '올바른 IPv4 주소, CIDR, 또는 IP 범위 형식이 아닙니다.\n예: 192.168.0.0/24, 10.0.0.30, 221.168.1.0-221.168.12.255',
      });
      return;
    }
    if (list.some((item) => item.cidr.toLowerCase() === value.toLowerCase())) {
      void dialog.alert({ title: '접근 가능 IP 대역', body: '이미 등록된 항목입니다.' });
      return;
    }
    const description = descriptionDraft.trim();
    const next = [...list, description ? { cidr: value, description } : { cidr: value }];
    if (await persist(next)) {
      setCidrDraft('');
      setDescriptionDraft('');
    }
  };

  const removeEntry = (cidr) => void persist(list.filter((item) => item.cidr !== cidr));

  const updateDescription = (cidr, text) => {
    const trimmed = text.trim();
    const next = list.map((item) => {
      if (item.cidr !== cidr) return item;
      return trimmed ? { cidr: item.cidr, description: text } : { cidr: item.cidr };
    });
    setList(next);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => void persist(next), 500);
  };

  const handleExport = () => {
    downloadTextFile(ipAllowlistExportFilename(), `${JSON.stringify(buildIpAllowlistPayload(list), null, 2)}\n`);
  };

  const handleImport = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const { allowedIpCidrs } = parseIpAllowlistPayload(await readFileAsText(file));
      const ok = await dialog.confirm({
        title: '가져오기',
        body:
          allowedIpCidrs.length === 0
            ? `「${file.name}」의 허용 IP가 비어 있습니다.\n현재 목록을 모두 지울까요?`
            : `「${file.name}」에서 허용 IP ${allowedIpCidrs.length}건을 가져옵니다.\n현재 목록을 이 내용으로 바꿀까요?`,
        confirmLabel: '가져오기',
      });
      if (ok) await persist(allowedIpCidrs);
    } catch (err) {
      void dialog.alert({
        title: '가져오기',
        body: err instanceof Error ? err.message : '가져오기에 실패했습니다.',
      });
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Section
        title="접근 가능 IP 대역"
        description={
          <>
            목록이 비어 있으면 모든 IP에서 접속할 수 있습니다. 항목을 추가하면 등록된 주소·대역·범위에서만 접속할 수
            있습니다. 단일 IP, CIDR(<code className={codeClass}>192.168.0.0/24</code>), 범위(
            <code className={codeClass}>221.168.1.0-221.168.12.255</code>) 형식을 지원하며 서버 PC의{' '}
            <code className={codeClass}>127.0.0.1</code> 은 항상 허용됩니다. VPN(Tailscale 등)은{' '}
            <code className={codeClass}>100.64.0.0/10</code> 을 등록하세요.
          </>
        }
      >
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <p className="m-0 text-xs text-slate-500">
            현재 접속 IP: <code className={codeClass}>{clientIp || '-'}</code>
          </p>
          <div className="flex gap-2">
            <button type="button" className={btnClass} disabled={saving} onClick={handleExport}>
              내보내기
            </button>
            <button type="button" className={btnClass} disabled={saving} onClick={() => importRef.current?.click()}>
              가져오기
            </button>
            <input
              ref={importRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(event) => void handleImport(event)}
            />
          </div>
        </div>

        <ul className="m-0 space-y-3 p-0">
          {list.length === 0 ? (
            <li className="list-none rounded-lg border border-dashed border-slate-300 px-3 py-3 text-sm text-slate-500">
              등록된 허용 IP가 없습니다. (모든 IP 허용)
            </li>
          ) : (
            list.map((entry) => (
              <li key={entry.cidr} className="list-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 break-all font-mono text-sm font-semibold text-slate-800">{entry.cidr}</span>
                  <button
                    type="button"
                    className={btnDangerClass}
                    disabled={saving}
                    onClick={() => removeEntry(entry.cidr)}
                  >
                    삭제
                  </button>
                </div>
                <label className="mt-2 flex items-center gap-2">
                  <span className="shrink-0 text-xs font-medium text-slate-500">설명</span>
                  <input
                    type="text"
                    className="min-w-0 flex-1 border-0 border-b border-slate-300 bg-transparent px-0 py-1 text-sm text-slate-800 outline-none focus:border-app-accent"
                    placeholder="예: 본사 사내망, VPN 대역"
                    value={entry.description ?? ''}
                    onChange={(event) => updateDescription(entry.cidr, event.target.value)}
                  />
                </label>
              </li>
            ))
          )}
        </ul>
      </Section>

      <Section title="IP 추가">
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void addEntry();
          }}
        >
          <Field label="허용 IP 주소">
            <input
              type="text"
              className={inputClass}
              placeholder="예: 192.168.0.0/24, 10.0.0.30, 221.168.1.0-221.168.12.255"
              value={cidrDraft}
              onChange={(event) => setCidrDraft(event.target.value)}
            />
          </Field>
          <Field label="설명 (선택)">
            <input
              type="text"
              className={inputClass}
              placeholder="예: 본사 사내망, VPN 대역"
              value={descriptionDraft}
              onChange={(event) => setDescriptionDraft(event.target.value)}
            />
          </Field>
          <button type="submit" className={btnPrimaryClass} disabled={saving}>
            {saving ? '저장 중…' : 'IP 추가'}
          </button>
        </form>
      </Section>
    </div>
  );
}
