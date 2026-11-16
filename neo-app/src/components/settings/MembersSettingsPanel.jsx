import { useState } from 'react';
import {
  LOGIN_ID_PATTERN,
  MIN_PASSWORD_LENGTH,
  memberRoleToLabel,
} from '../../../shared/members.js';
import { api } from '../../lib/apiClient.js';
import { useAuth } from '../../context/AuthContext.jsx';
import { useDialog } from '../../context/DialogContext.jsx';
import { useLoad } from '../../hooks/useLoad.js';
import { formatDateTime } from '../../lib/format.js';
import {
  Badge,
  Field,
  LoadError,
  Loading,
  Section,
  btnClass,
  btnDangerClass,
  btnPrimaryClass,
  inputClass,
} from './ui.jsx';

const AUDIT_TONE = { success: 'green', fail: 'amber', locked: 'red' };
const AUDIT_LABEL = { success: '성공', fail: '실패', locked: '잠금' };

/**
 * Create / edit dialog. `member` null = new member.
 *
 * @param {{
 *   member: import('../../../shared/members.js').PublicMember | null,
 *   isSelf: boolean,
 *   onClose: () => void,
 *   onSaved: () => void,
 * }} props
 */
function MemberEditor({ member, isSelf, onClose, onSaved }) {
  const creating = !member;
  const [loginId, setLoginId] = useState(member?.loginId ?? '');
  const [displayName, setDisplayName] = useState(member?.displayName ?? '');
  const [role, setRole] = useState(member?.role ?? 'member');
  const [active, setActive] = useState(member?.active ?? true);
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const lockRole = member?.isBootstrapAdmin || isSelf;
  const lockActive = member?.isBootstrapAdmin || isSelf;

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    if (creating && !LOGIN_ID_PATTERN.test(loginId.trim())) {
      setError('아이디는 영문·숫자·. _ - 조합 2~32자여야 합니다.');
      return;
    }
    if ((creating || password) && password.length < MIN_PASSWORD_LENGTH) {
      setError(`비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`);
      return;
    }
    setSaving(true);
    try {
      if (creating) {
        await api('members.create', { loginId: loginId.trim(), displayName, password, role, active });
      } else {
        await api('members.update', { id: member.id, displayName, role, active, password });
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장하지 못했습니다.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-[400px] rounded-xl bg-white p-6 shadow-xl"
        role="dialog"
        aria-modal="true"
      >
        <h2 className="m-0 text-lg font-medium text-slate-900">{creating ? '회원 추가' : '회원 수정'}</h2>
        <div className="mt-4 space-y-3">
          <Field label="아이디">
            <input
              className={inputClass}
              value={loginId}
              disabled={!creating || saving}
              autoComplete="off"
              onChange={(event) => setLoginId(event.target.value)}
            />
          </Field>
          <Field label="이름 (표시용)">
            <input
              className={inputClass}
              value={displayName}
              disabled={saving}
              maxLength={40}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </Field>
          <Field
            label={creating ? '비밀번호' : '새 비밀번호'}
            hint={creating ? `${MIN_PASSWORD_LENGTH}자 이상` : '변경할 때만 입력하세요. 변경하면 해당 회원은 다시 로그인해야 합니다.'}
          >
            <input
              type="password"
              className={inputClass}
              value={password}
              disabled={saving}
              autoComplete="new-password"
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <Field label="권한" hint={lockRole ? '이 계정의 권한은 변경할 수 없습니다.' : undefined}>
            <select
              className={inputClass}
              value={role}
              disabled={saving || lockRole}
              onChange={(event) => setRole(event.target.value)}
            >
              <option value="member">{memberRoleToLabel('member')}</option>
              <option value="super_admin">{memberRoleToLabel('super_admin')} (환경설정 가능)</option>
            </select>
          </Field>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="h-4 w-4 accent-app-accent"
              checked={active}
              disabled={saving || lockActive}
              onChange={(event) => setActive(event.target.checked)}
            />
            사용(로그인 허용)
          </label>
        </div>
        {error ? (
          <p className="mt-3 text-sm text-[#c5221f]" role="alert">
            {error}
          </p>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={btnClass} disabled={saving} onClick={onClose}>
            취소
          </button>
          <button type="submit" className={btnPrimaryClass} disabled={saving}>
            {saving ? '저장 중…' : '저장'}
          </button>
        </div>
      </form>
    </div>
  );
}

function LoginAuditSection() {
  const dialog = useDialog();
  const [open, setOpen] = useState(false);
  const { data, loading, error, reload } = useLoad(() => api('audit.list'));

  const handleClear = async () => {
    const ok = await dialog.confirm({
      title: '로그인 기록 지우기',
      body: '모든 로그인 기록을 삭제할까요?',
      confirmLabel: '지우기',
      confirmVariant: 'danger',
    });
    if (!ok) return;
    await api('audit.clear');
    await reload();
  };

  return (
    <Section
      title="로그인 기록"
      description="최근 로그인 시도(성공 / 실패 / 잠금)와 접속 IP입니다. 최대 500건 보관합니다."
      actions={
        <>
          <button type="button" className={btnClass} onClick={() => setOpen((v) => !v)}>
            {open ? '접기' : '펼치기'}
          </button>
          {open ? (
            <>
              <button type="button" className={btnClass} onClick={() => void reload()}>
                새로고침
              </button>
              <button type="button" className={btnDangerClass} onClick={() => void handleClear()}>
                모두 지우기
              </button>
            </>
          ) : null}
        </>
      }
    >
      {!open ? null : loading && !data ? (
        <Loading />
      ) : error ? (
        <LoadError message={error} onRetry={reload} />
      ) : (
        <div className="max-h-72 overflow-auto rounded-md border border-slate-200">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">시각</th>
                <th className="px-3 py-2 font-medium">아이디</th>
                <th className="px-3 py-2 font-medium">결과</th>
                <th className="px-3 py-2 font-medium">IP</th>
              </tr>
            </thead>
            <tbody>
              {data?.entries.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-slate-400">
                    기록이 없습니다.
                  </td>
                </tr>
              ) : (
                data?.entries.map((entry) => (
                  <tr key={entry.id} className="border-t border-slate-100">
                    <td className="whitespace-nowrap px-3 py-1.5 text-slate-600">{formatDateTime(entry.at)}</td>
                    <td className="px-3 py-1.5 text-slate-800">{entry.loginId}</td>
                    <td className="px-3 py-1.5">
                      <Badge tone={AUDIT_TONE[entry.result] ?? 'slate'}>{AUDIT_LABEL[entry.result] ?? entry.result}</Badge>
                    </td>
                    <td className="px-3 py-1.5 font-mono text-xs text-slate-600">{entry.ip || '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

export default function MembersSettingsPanel() {
  const dialog = useDialog();
  const { user } = useAuth();
  const { data, loading, error, reload } = useLoad(() => api('members.list'));
  const [editing, setEditing] = useState(
    /** @type {{ member: import('../../../shared/members.js').PublicMember | null } | null} */ (null),
  );

  if (loading && !data) return <Loading />;
  if (error || !data) return <LoadError message={error} onRetry={reload} />;

  const handleDelete = async (member) => {
    const ok = await dialog.confirm({
      title: '회원 삭제',
      body: `「${member.loginId}」 회원을 삭제할까요?\n삭제하면 되돌릴 수 없습니다.`,
      confirmLabel: '삭제',
      confirmVariant: 'danger',
    });
    if (!ok) return;
    try {
      await api('members.delete', { id: member.id });
      await reload();
    } catch (err) {
      void dialog.alert({ title: '회원 삭제', body: err instanceof Error ? err.message : '삭제하지 못했습니다.' });
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <Section
        title="회원 목록"
        description="총괄관리자는 환경설정을 사용할 수 있고, 일반사용자는 기능 화면만 사용합니다."
        actions={
          <button type="button" className={btnPrimaryClass} onClick={() => setEditing({ member: null })}>
            회원 추가
          </button>
        }
      >
        <div className="overflow-auto rounded-md border border-slate-200">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">아이디</th>
                <th className="px-3 py-2 font-medium">이름</th>
                <th className="px-3 py-2 font-medium">권한</th>
                <th className="px-3 py-2 font-medium">상태</th>
                <th className="px-3 py-2 font-medium">등록일</th>
                <th className="px-3 py-2 text-right font-medium">관리</th>
              </tr>
            </thead>
            <tbody>
              {data.members.map((member) => {
                const isSelf = member.id === user?.id;
                return (
                  <tr key={member.id} className="border-t border-slate-100">
                    <td className="px-3 py-2 font-medium text-slate-800">
                      {member.loginId}
                      {member.isBootstrapAdmin ? (
                        <span className="ml-2">
                          <Badge tone="slate">기본</Badge>
                        </span>
                      ) : null}
                      {isSelf ? (
                        <span className="ml-2">
                          <Badge>나</Badge>
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-slate-600">{member.displayName}</td>
                    <td className="px-3 py-2">
                      <Badge tone={member.role === 'super_admin' ? 'amber' : 'slate'}>
                        {memberRoleToLabel(member.role)}
                      </Badge>
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={member.active ? 'green' : 'red'}>{member.active ? '사용' : '중지'}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-500">
                      {formatDateTime(member.createdAt).slice(0, 10)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-1.5">
                        <button type="button" className={btnClass} onClick={() => setEditing({ member })}>
                          수정
                        </button>
                        <button
                          type="button"
                          className={btnDangerClass}
                          disabled={member.isBootstrapAdmin || isSelf}
                          onClick={() => void handleDelete(member)}
                        >
                          삭제
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      <LoginAuditSection />

      {editing ? (
        <MemberEditor
          member={editing.member}
          isSelf={editing.member?.id === user?.id}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}
