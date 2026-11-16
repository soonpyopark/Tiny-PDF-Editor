import { useEffect, useState } from 'react';
import { api } from '../../lib/apiClient.js';
import { useAppInfo } from '../../context/AppInfoContext.jsx';
import { useAuth } from '../../context/AuthContext.jsx';
import { formatDateTime } from '../../lib/format.js';

function Stat({ label, value }) {
  return (
    <div className="rounded-lg border border-app-border bg-white px-4 py-3 shadow-sm">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 truncate text-lg font-semibold text-slate-800">{value}</div>
    </div>
  );
}

/** Sample feature screen. Replace it, or copy the folder to start a new feature. */
export default function HomePage() {
  const appInfo = useAppInfo();
  const { user } = useAuth();
  const [summary, setSummary] = useState(/** @type {any} */ (null));
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api('home.summary')
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '불러오지 못했습니다.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="h-full overflow-auto p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <section>
          <h1 className="m-0 text-xl font-semibold text-slate-900">
            {user?.displayName || user?.loginId}님, 환영합니다
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {appInfo.name} 기본 프레임입니다. 이 영역에 기능 화면이 들어갑니다.
          </p>
        </section>

        <section className="grid gap-3 sm:grid-cols-3">
          <Stat label="서버 시간" value={summary ? formatDateTime(summary.serverTime) : '…'} />
          <Stat label="내 접속 IP" value={summary?.clientIp ?? '…'} />
          <Stat label="등록 회원" value={summary ? `${summary.memberCount}명` : '…'} />
        </section>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}

        <section className="rounded-lg border border-app-border bg-white p-5 shadow-sm">
          <h2 className="m-0 text-sm font-semibold text-slate-800">기능 추가 방법</h2>
          <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-slate-600">
            <li>
              화면: <code className="rounded bg-slate-100 px-1 text-[12px]">src/features/&lt;id&gt;/</code> 를 만들고{' '}
              <code className="rounded bg-slate-100 px-1 text-[12px]">src/features/registry.js</code> 에 한 줄 등록
            </li>
            <li>
              서버 API:{' '}
              <code className="rounded bg-slate-100 px-1 text-[12px]">electron/modules/&lt;name&gt;.js</code> 에{' '}
              <code className="rounded bg-slate-100 px-1 text-[12px]">defineApi()</code> 로 등록 후{' '}
              <code className="rounded bg-slate-100 px-1 text-[12px]">electron/modules/index.js</code> 에 추가
            </li>
            <li>
              화면에서 호출: <code className="rounded bg-slate-100 px-1 text-[12px]">api(&apos;이름&apos;, 본문)</code>
            </li>
          </ol>
        </section>
      </div>
    </div>
  );
}
