import { useEffect, useState } from 'react';
import { DEFAULT_PORT } from '../../../shared/constants.js';
import { api, apiDownload, getNative, saveBlob } from '../../lib/apiClient.js';
import { useAuth } from '../../context/AuthContext.jsx';
import { useDialog } from '../../context/DialogContext.jsx';
import { useLoad } from '../../hooks/useLoad.js';
import { copyText, formatDateTime } from '../../lib/format.js';
import {
  Badge,
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

const MODES = [
  {
    id: 'local',
    label: '이 PC에서만 (127.0.0.1)',
    hint: '다른 기기는 접속할 수 없습니다. 가장 안전한 기본값입니다.',
  },
  {
    id: 'lan',
    label: 'LAN / VPN 허용 (0.0.0.0)',
    hint: '같은 네트워크의 브라우저에서 접속할 수 있습니다. 접근 가능 IP 대역과 함께 사용하세요.',
  },
];

export default function ServerSettingsPanel() {
  const dialog = useDialog();
  const { clientIp } = useAuth();
  const { data: info, loading, error, reload } = useLoad(() => api('server.info'));
  const [port, setPort] = useState('');
  const [mode, setMode] = useState('local');
  const [applying, setApplying] = useState(false);
  const [copied, setCopied] = useState('');
  const [tlsHosts, setTlsHosts] = useState('');
  const [tlsBusy, setTlsBusy] = useState(false);
  const native = getNative();

  useEffect(() => {
    if (!info) return;
    setPort(String(info.port ?? DEFAULT_PORT));
    setMode(info.mode ?? 'local');
    setTlsHosts((info.tlsHostnames ?? []).join('\n'));
  }, [info]);

  if (loading && !info) return <Loading />;
  if (error || !info) return <LoadError message={error} onRetry={reload} />;

  const dirty = Number(port) !== info.port || mode !== info.mode;

  const handleCopy = async (url) => {
    await copyText(url);
    setCopied(url);
    window.setTimeout(() => setCopied(''), 1500);
  };

  const handleApply = async () => {
    const remote = clientIp && clientIp !== '127.0.0.1';
    const lines = [
      `포트 ${info.port} → ${port}`,
      `범위 ${info.mode === 'lan' ? 'LAN/VPN' : '이 PC만'} → ${mode === 'lan' ? 'LAN/VPN' : '이 PC만'}`,
      '',
      '서버를 다시 시작하며 화면이 새 주소로 이동합니다. 포트가 바뀌면 다시 로그인해야 할 수 있습니다.',
    ];
    if (remote && mode === 'local') {
      lines.push('', '⚠ 현재 원격 기기에서 접속 중입니다. "이 PC에서만"으로 바꾸면 이 연결이 끊어집니다.');
    }
    const ok = await dialog.confirm({
      title: '서버 설정 적용',
      body: lines.join('\n'),
      confirmLabel: '적용',
    });
    if (!ok) return;

    setApplying(true);
    try {
      const result = await api('server.apply', { port: Number(port), mode });
      if (result.restarting) {
        followRestart(result);
        return;
      }
      await reload();
      setApplying(false);
    } catch (err) {
      setApplying(false);
      void dialog.alert({
        title: '서버 설정',
        body: err instanceof Error ? err.message : '적용하지 못했습니다.',
      });
    }
  };

  /** Browsers keep their host name; the Electron window is always local. */
  const followRestart = (result) => {
    window.setTimeout(() => {
      window.location.href = `${result.scheme}://${window.location.hostname}:${result.port}/`;
    }, 1500);
  };

  /**
   * HTTPS actions always re-send the *running* port / mode, so unsaved edits in
   * the 접속 설정 form are never applied by accident.
   *
   * @param {Record<string, unknown>} extra
   * @param {string} failure
   */
  const applyTls = async (extra, failure) => {
    setTlsBusy(true);
    try {
      const result = await api('server.apply', { port: info.port, mode: info.mode, ...extra });
      if (result.restarting) {
        setApplying(true);
        followRestart(result);
        return;
      }
      await reload();
      setTlsBusy(false);
    } catch (err) {
      setTlsBusy(false);
      void dialog.alert({ title: 'HTTPS', body: err instanceof Error ? err.message : failure });
    }
  };

  const handleToggleHttps = async () => {
    const enable = !info.httpsEnabled;
    const lines = enable
      ? [
          'HTTPS를 켜면 서버가 다시 시작되고 주소가 https:// 로 바뀝니다.',
          '주소가 바뀌므로 다시 로그인해야 합니다.',
          '',
          '이 프로그램 창은 자체 인증서를 자동으로 신뢰합니다. 다른 기기의 브라우저는 "CA 인증서 받기"로 받은 인증서를 한 번 설치해야 경고가 사라집니다.',
        ]
      : ['HTTPS를 끄면 서버가 다시 시작되고 주소가 http:// 로 바뀝니다.', '주소가 바뀌므로 다시 로그인해야 합니다.'];
    const ok = await dialog.confirm({
      title: enable ? 'HTTPS 켜기' : 'HTTPS 끄기',
      body: lines.join('\n'),
      confirmLabel: enable ? '켜기' : '끄기',
    });
    if (ok) await applyTls({ httpsEnabled: enable }, 'HTTPS 설정을 바꾸지 못했습니다.');
  };

  const handleSaveHosts = () =>
    applyTls({ tlsHostnames: tlsHosts }, '추가 호스트를 저장하지 못했습니다.');

  const handleRegenerate = async () => {
    const ok = await dialog.confirm({
      title: '인증서 다시 만들기',
      body: `현재 LAN IP와 추가 호스트를 넣어 서버 인증서를 다시 만듭니다.${
        info.httpsEnabled ? '\nHTTPS가 켜져 있어 서버가 다시 시작됩니다.' : ''
      }\n\nCA 인증서는 바뀌지 않으므로 다른 기기에 다시 설치할 필요가 없습니다.`,
      confirmLabel: '다시 만들기',
    });
    if (ok) await applyTls({ regenerateTls: true }, '인증서를 다시 만들지 못했습니다.');
  };

  const handleDownloadCa = async () => {
    try {
      saveBlob(await apiDownload('server.caDownload'), 'TinyPDFEditor-NEO-ca.crt');
      void reload();
    } catch (err) {
      void dialog.alert({
        title: 'CA 인증서',
        body: err instanceof Error ? err.message : '인증서를 받지 못했습니다.',
      });
    }
  };

  const tls = info.tls ?? {};
  const hostsDirty = tlsHosts.split(/[\s,;]+/).filter(Boolean).join(',') !== (info.tlsHostnames ?? []).join(',');

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Section
        title="서버 상태"
        description="화면(Electron 창)과 LAN 브라우저가 같은 웹 서버를 사용합니다."
        actions={
          <button type="button" className={btnClass} onClick={() => void reload()}>
            새로고침
          </button>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={info.running ? 'green' : 'red'}>{info.running ? '실행 중' : '중지됨'}</Badge>
          <Badge tone="slate">포트 {info.port}</Badge>
          <Badge tone={info.httpsEnabled ? 'green' : 'default'}>{info.httpsEnabled ? 'HTTPS' : 'HTTP'}</Badge>
          <Badge tone={info.mode === 'lan' ? 'amber' : 'default'}>
            {info.mode === 'lan' ? 'LAN / VPN 허용' : '이 PC에서만'}
          </Badge>
        </div>

        <ul className="mt-4 space-y-2">
          {info.urls.map((url) => (
            <li
              key={url}
              className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2"
            >
              <code className="min-w-0 break-all text-sm text-slate-800">{url}</code>
              <button type="button" className={btnClass} onClick={() => void handleCopy(url)}>
                {copied === url ? '복사됨' : '복사'}
              </button>
            </li>
          ))}
        </ul>
        {info.mode === 'local' && info.addresses.length > 0 ? (
          <p className="mt-2 text-xs text-slate-500">
            이 PC의 네트워크 주소: <code className={codeClass}>{info.addresses.join(', ')}</code> — LAN 접속을 허용하면
            이 주소로 접속할 수 있습니다.
          </p>
        ) : null}
      </Section>

      <Section title="접속 설정" description="변경하면 서버가 다시 시작됩니다.">
        <div className="flex flex-col gap-5">
          <Field label="포트" hint={`1024~65535 (기본 ${DEFAULT_PORT})`}>
            <input
              type="number"
              min={1024}
              max={65535}
              className={`${inputClass} max-w-[180px]`}
              value={port}
              disabled={applying}
              onChange={(event) => setPort(event.target.value)}
            />
          </Field>

          <fieldset className="m-0 flex flex-col gap-2 border-0 p-0" disabled={applying}>
            <legend className="mb-2 p-0 text-xs font-medium text-slate-600">접속 허용 범위</legend>
            {MODES.map((item) => (
              <label
                key={item.id}
                className={`flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 ${
                  mode === item.id ? 'border-app-accentBorder bg-app-accentSoft' : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <input
                  type="radio"
                  name="server-mode"
                  className="mt-1 accent-app-accent"
                  checked={mode === item.id}
                  onChange={() => setMode(item.id)}
                />
                <span>
                  <span className="block text-sm font-medium text-slate-800">{item.label}</span>
                  <span className="block text-xs text-slate-500">{item.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div className="flex items-center gap-3 border-t border-slate-100 pt-4">
            <button
              type="button"
              className={btnPrimaryClass}
              disabled={!dirty || applying || !port}
              onClick={() => void handleApply()}
            >
              {applying ? '적용 중…' : '적용 (서버 재시작)'}
            </button>
            {dirty && !applying ? (
              <button
                type="button"
                className={btnClass}
                onClick={() => {
                  setPort(String(info.port));
                  setMode(info.mode);
                }}
              >
                되돌리기
              </button>
            ) : null}
          </div>
          <p className="text-xs leading-relaxed text-slate-400">
            LAN 접속이 안 되면 Windows 방화벽에서 이 프로그램(또는 해당 포트)의 인바운드 연결을 허용해야 합니다. 설정은{' '}
            <code className={codeClass}>settings.json</code> 에 저장되며 <code className={codeClass}>.env</code> 의{' '}
            <code className={codeClass}>APP_PORT</code> / <code className={codeClass}>APP_HOST</code> 보다 우선합니다.
          </p>
        </div>
      </Section>

      <Section
        title="HTTPS"
        description="같은 포트에서 TLS로 암호화합니다. 이 프로그램 창은 자체 인증서를 자동으로 신뢰하고, 다른 기기의 브라우저는 CA 인증서를 한 번 설치해야 경고가 사라집니다."
      >
        <div className="flex flex-col gap-5">
          <dl className="grid gap-2 text-sm text-slate-700 sm:grid-cols-[6rem_1fr]">
            <dt className="text-slate-500">상태</dt>
            <dd>
              <Badge tone={info.httpsEnabled ? 'green' : 'default'}>{info.httpsEnabled ? '켜짐' : '꺼짐'}</Badge>
            </dd>
            <dt className="text-slate-500">인증서 대상</dt>
            <dd className="break-all">
              {tls.sans?.length ? tls.sans.join(', ') : '아직 만들지 않음 (HTTPS를 켜면 자동 생성)'}
            </dd>
            <dt className="text-slate-500">만료</dt>
            <dd>{tls.notAfter ? formatDateTime(tls.notAfter) : '—'}</dd>
            <dt className="text-slate-500">폴더</dt>
            <dd className="break-all">
              <code className={codeClass}>{tls.dir || '—'}</code>
            </dd>
          </dl>

          <Field
            label="추가 호스트 (DDNS 등)"
            hint="줄 또는 쉼표로 여러 개를 입력합니다. 인증서 대상에 포함되며, HTTPS가 켜져 있으면 저장 시 서버가 다시 시작됩니다. LAN IP는 자동으로 포함됩니다."
          >
            <textarea
              className={`${inputClass} min-h-[4.5rem] font-mono`}
              spellCheck={false}
              placeholder="xxx.iptime.org"
              value={tlsHosts}
              disabled={applying || tlsBusy}
              onChange={(event) => setTlsHosts(event.target.value)}
            />
          </Field>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={info.httpsEnabled ? btnDangerClass : btnPrimaryClass}
              disabled={applying || tlsBusy}
              onClick={() => void handleToggleHttps()}
            >
              {info.httpsEnabled ? 'HTTPS 끄기' : 'HTTPS 켜기'}
            </button>
            <button
              type="button"
              className={btnClass}
              disabled={applying || tlsBusy || !hostsDirty}
              onClick={() => void handleSaveHosts()}
            >
              추가 호스트 저장
            </button>
            <button
              type="button"
              className={btnClass}
              disabled={applying || tlsBusy}
              onClick={() => void handleRegenerate()}
            >
              인증서 다시 만들기
            </button>
            <button type="button" className={btnClass} disabled={applying || tlsBusy} onClick={() => void handleDownloadCa()}>
              CA 인증서 받기
            </button>
            {native?.openStateFolder ? (
              <button type="button" className={btnClass} onClick={() => void native.openStateFolder('tls')}>
                인증서 폴더 열기
              </button>
            ) : null}
          </div>

          <p className="text-xs leading-relaxed text-slate-400">
            CA 설치: Windows는 받은 <code className={codeClass}>.crt</code>를 열어 &quot;인증서 설치 → 로컬 컴퓨터 → 신뢰할 수
            있는 루트 인증 기관&quot;에 넣습니다. 휴대폰은 파일을 열어 인증서로 설치합니다. 인증서 개인키(
            <code className={codeClass}>ca.key</code>, <code className={codeClass}>server.key</code>)는 폴더 밖으로
            내보내지 마세요. HTTPS를 켜면 주소의 http:// 부분이 https:// 로 바뀌므로 다시 로그인해야 합니다.
          </p>
        </div>
      </Section>
    </div>
  );
}
