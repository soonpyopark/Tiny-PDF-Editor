import { useEffect, useRef, useState } from 'react';
import { useDialog } from '../../context/DialogContext.jsx';
import { api } from '../../lib/apiClient.js';

/**
 * PDF 병합 대화상자 (Tiny merge_pdf_dialog.py 의 규칙을 옮긴 것).
 * - 파일 추가 / 폴더에서 추가 / 끌어다 놓기, 목록에서 드래그로 순서 변경
 * - 선택 제거, 파일 이름(기본 "{첫 파일}_병합"), 저장 폴더(기억)
 * - 선택한 파일의 첫 쪽 미리보기, 암호 PDF는 해당 파일에서 바로 비밀번호 입력
 * - 같은 이름이 있으면 덮어쓰기 확인 후 저장, 완료되면 저장한 파일을 연다
 */

const DEFAULT_NAME = '병합';
const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'flex h-[min(600px,calc(100vh-48px))] w-full max-w-[920px] flex-col overflow-hidden rounded-xl bg-white shadow-xl';
const fieldClass =
  'h-9 w-full rounded-md border border-slate-300 bg-white px-2.5 text-sm text-slate-800 outline-none focus:border-app-accent';
const btnBase = 'inline-flex h-9 items-center justify-center rounded-full px-4 text-sm font-medium transition-colors disabled:cursor-default disabled:opacity-50';
const btnPrimary = `${btnBase} bg-app-accent px-6 text-white hover:bg-app-accentHover disabled:hover:bg-app-accent`;
const btnGhost = `${btnBase} text-slate-700 hover:bg-slate-100`;
const btnOutline = `${btnBase} border border-app-accentBorder text-app-accentText hover:bg-app-accentSoft`;

function baseName(filePath) {
  return filePath.split(/[\\/]/).pop() || filePath;
}

function stem(filePath) {
  const name = baseName(filePath);
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(0, dot) : name;
}

/**
 * @param {{
 *   open: boolean,
 *   onClose: () => void,
 *   onMerged: (path: string) => void,
 * }} props
 */
export default function MergePdfDialog({ open, onClose, onMerged }) {
  const dialog = useDialog();
  const [files, setFiles] = useState(/** @type {{ key: string, path: string, pages: number | null, locked: boolean }[]} */ ([]));
  const [selectedKeys, setSelectedKeys] = useState(/** @type {string[]} */ ([]));
  const [anchorKey, setAnchorKey] = useState(/** @type {string | null} */ (null));
  const [outputName, setOutputName] = useState(DEFAULT_NAME);
  const [outputFolder, setOutputFolder] = useState('');
  const [passwords, setPasswords] = useState(/** @type {Record<string, string>} */ ({}));
  const [passwordFor, setPasswordFor] = useState(/** @type {null | { path: string, rejected: boolean }} */ (null));
  const [passwordInput, setPasswordInput] = useState('');
  const [preview, setPreview] = useState(/** @type {null | { status: string, src?: string, pageCount?: number, rejected?: boolean, message?: string }} */ (null));
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [dragKey, setDragKey] = useState(/** @type {string | null} */ (null));
  const [dropKey, setDropKey] = useState(/** @type {string | null} */ (null));
  const [externalDrop, setExternalDrop] = useState(false);
  const keySeq = useRef(0);
  const previewToken = useRef(0);

  const currentFile = files.find((file) => file.key === anchorKey) ?? files[0] ?? null;
  const currentPath = currentFile?.path ?? '';
  const currentPassword = passwords[currentPath] ?? '';

  // Reset every time the dialog opens; remember the save folder like the original.
  useEffect(() => {
    if (!open) return;
    setFiles([]);
    setSelectedKeys([]);
    setAnchorKey(null);
    setOutputName(DEFAULT_NAME);
    setPasswords({});
    setPasswordFor(null);
    setPasswordInput('');
    setPreview(null);
    setBusy('');
    setError('');
    setMenuOpen(false);
    api('pdf.mergeState')
      .then((state) => setOutputFolder(state.saveFolder || ''))
      .catch(() => setOutputFolder(''));
  }, [open]);

  // First-page preview of the current file (re-runs when its password changes).
  useEffect(() => {
    if (!open || !currentPath) {
      setPreview(null);
      return;
    }
    const token = ++previewToken.current;
    setPreview({ status: 'loading' });
    api('pdf.mergePreview', { path: currentPath, password: currentPassword || undefined })
      .then((result) => {
        if (token !== previewToken.current) return;
        if (result.needsPassword) {
          setPreview({ status: 'needsPassword', rejected: result.rejected });
          setPasswordFor({ path: currentPath, rejected: Boolean(result.rejected) });
        } else if (result.unsupported) {
          setPreview({ status: 'unsupported' });
        } else {
          setPreview({ status: 'ok', src: `data:image/png;base64,${result.png}`, pageCount: result.pageCount });
        }
      })
      .catch((err) => {
        if (token === previewToken.current) setPreview({ status: 'error', message: err.message });
      });
  }, [open, currentPath, currentPassword]);

  if (!open) return null;

  async function refreshPages(paths, nextPasswords) {
    try {
      const result = await api('pdf.mergeInspect', { paths, passwords: nextPasswords });
      setFiles((prev) =>
        prev.map((file) => {
          const item = result.items.find((entry) => entry.path === file.path);
          return item ? { ...file, pages: item.pages ?? null, locked: Boolean(item.needsPassword) } : file;
        }),
      );
    } catch (err) {
      setError(err.message || '페이지 수를 읽지 못했습니다.');
    }
  }

  async function addPaths(paths) {
    setError('');
    const seen = new Set(files.map((file) => file.path.toLowerCase()));
    const fresh = [...new Set(paths)].filter((item) => {
      const key = item.toLowerCase();
      if (!item || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    if (!fresh.length) return;
    const created = fresh.map((path) => ({
      key: `f${++keySeq.current}`,
      path,
      pages: null,
      locked: false,
    }));
    // 원본: 첫 파일을 넣을 때 기본 이름이면 "{첫 파일 이름}_병합"으로 바꾼다.
    if (files.length === 0 && (outputName.trim() === '' || outputName === DEFAULT_NAME)) {
      setOutputName(`${stem(created[0].path)}_${DEFAULT_NAME}`);
    }
    setFiles((prev) => [...prev, ...created]);
    setAnchorKey(created[0].key);
    setSelectedKeys([created[0].key]);
    void refreshPages(fresh, passwords);
  }

  async function pickFiles() {
    setMenuOpen(false);
    try {
      const result = await api('pdf.mergePickFiles');
      if (result.canceled) return;
      await addPaths(result.paths);
    } catch (err) {
      setError(err.message || '파일을 고르지 못했습니다.');
    }
  }

  async function pickFolder() {
    setMenuOpen(false);
    try {
      const result = await api('pdf.mergePickFolder');
      if (result.canceled) return;
      if (!result.paths.length) {
        void dialog.alert({
          title: 'PDF 병합',
          body: '선택한 폴더에 PDF, 이미지 또는 한글(HWP/HWPX) 파일이 없습니다.',
        });
        return;
      }
      await addPaths(result.paths);
    } catch (err) {
      setError(err.message || '폴더를 읽지 못했습니다.');
    }
  }

  async function pickSaveFolder() {
    try {
      const result = await api('pdf.mergePickSaveFolder');
      if (result.canceled) return;
      setOutputFolder(result.folder);
    } catch (err) {
      setError(err.message || '저장 폴더를 고르지 못했습니다.');
    }
  }

  function removeSelected() {
    const removeSet = new Set(selectedKeys);
    setFiles((prev) => prev.filter((file) => !removeSet.has(file.key)));
    setSelectedKeys([]);
    setAnchorKey(null);
  }

  function moveFile(fromKey, toKey) {
    if (fromKey === toKey) return;
    setFiles((prev) => {
      const from = prev.findIndex((file) => file.key === fromKey);
      const to = prev.findIndex((file) => file.key === toKey);
      if (from < 0 || to < 0) return prev;
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }

  function onItemClick(event, key) {
    if (event.shiftKey && anchorKey) {
      const from = files.findIndex((file) => file.key === anchorKey);
      const to = files.findIndex((file) => file.key === key);
      const [start, end] = [Math.min(from, to), Math.max(from, to)];
      setSelectedKeys(files.slice(start, end + 1).map((file) => file.key));
      return;
    }
    if (event.ctrlKey || event.metaKey) {
      setSelectedKeys((prev) => (prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]));
      setAnchorKey(key);
      return;
    }
    setSelectedKeys([key]);
    setAnchorKey(key);
  }

  function onExternalDrop(event) {
    event.preventDefault();
    setExternalDrop(false);
    if (!event.dataTransfer.types.includes('Files')) return;
    const paths = Array.from(event.dataTransfer.files || [])
      .map((file) => window.frame?.pathForFile?.(file) || '')
      .filter(Boolean);
    if (!paths.length) {
      setError('이 화면에서는 끌어다 놓기를 쓸 수 없습니다. 파일 추가를 눌러 주세요.');
      return;
    }
    void addPaths(paths);
  }

  async function submitPassword(event) {
    event.preventDefault();
    if (!passwordFor || !passwordInput) return;
    const path = passwordFor.path;
    const next = { ...passwords, [path]: passwordInput };
    setPasswords(next);
    setPasswordFor(null);
    setPasswordInput('');
    void refreshPages([path], next);
  }

  async function runMerge({ overwrite = false } = {}) {
    if (!files.length || busy) return;
    setError('');
    setBusy('병합하는 중…');
    try {
      const result = await api('pdf.mergeRun', {
        paths: files.map((file) => file.path),
        name: outputName,
        folder: outputFolder,
        passwords,
        overwrite,
      });
      setBusy('');
      if (result.needsPassword) {
        setAnchorKey(files.find((file) => file.path === result.path)?.key ?? anchorKey);
        setPasswordFor({ path: result.path, rejected: Boolean(result.rejected) });
        setError(result.rejected ? '비밀번호가 올바르지 않습니다.' : '암호가 걸린 파일입니다. 비밀번호를 입력해 주세요.');
        return;
      }
      if (result.exists) {
        const ok = await dialog.confirm({
          title: 'PDF 병합',
          body: `같은 이름의 파일이 있습니다.\n덮어쓰시겠습니까?\n\n${result.target}`,
          confirmLabel: '덮어쓰기',
          confirmVariant: 'danger',
        });
        if (ok) await runMerge({ overwrite: true });
        return;
      }
      onMerged(result.path);
    } catch (err) {
      setBusy('');
      setError(err.message || '병합하지 못했습니다.');
    }
  }

  const passwordNeeded = passwordFor && currentPath === passwordFor.path;
  const pageTotal = files.reduce((sum, file) => sum + (file.pages ?? 0), 0);

  return (
    <div className={overlayClass} role="presentation" onClick={busy ? undefined : onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="merge-pdf-title"
        className={cardClass}
        onClick={(event) => {
          event.stopPropagation();
          setMenuOpen(false);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !busy) onClose();
          const onControl = event.target instanceof HTMLInputElement || event.target instanceof HTMLButtonElement;
          if (event.key === 'Enter' && !onControl) {
            event.preventDefault();
            void runMerge();
          }
        }}
      >
        <header className="flex items-center gap-3 border-b border-slate-200 px-6 py-4">
          <div className="min-w-0 flex-1">
            <h2 id="merge-pdf-title" className="m-0 text-lg font-semibold text-slate-900">
              PDF 병합
            </h2>
            <p className="m-0 mt-0.5 text-xs text-slate-500">
              목록 순서대로 합칩니다. 끌어서 순서를 바꾸거나 파일을 끌어다 놓을 수 있습니다.
            </p>
          </div>
          <button type="button" className={btnGhost} onClick={onClose} disabled={Boolean(busy)}>
            닫기
          </button>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_280px] gap-5 px-6 py-5">
          <section className="flex min-h-0 flex-col gap-3">
            <div className="flex items-center gap-2">
              <div className="relative">
                <button
                  type="button"
                  className={btnPrimary}
                  aria-haspopup="menu"
                  aria-expanded={menuOpen}
                  onClick={(event) => {
                    event.stopPropagation();
                    setMenuOpen((value) => !value);
                  }}
                >
                  파일 추가 ▾
                </button>
                {menuOpen ? (
                  <div
                    role="menu"
                    className="absolute left-0 top-full z-10 mt-1 w-44 rounded-md border border-slate-200 bg-white py-1 shadow-lg"
                  >
                    <button type="button" role="menuitem" className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-100" onClick={pickFiles}>
                      파일 추가...
                    </button>
                    <button type="button" role="menuitem" className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-100" onClick={pickFolder}>
                      폴더에서 추가...
                    </button>
                  </div>
                ) : null}
              </div>
              <button type="button" className={btnOutline} disabled={!selectedKeys.length} onClick={removeSelected}>
                선택 제거
              </button>
              <span className="ml-auto text-xs text-slate-500">
                {files.length ? `${files.length}개 파일 · ${pageTotal}페이지` : ''}
              </span>
            </div>

            <div
              className={`min-h-0 flex-1 overflow-auto rounded-lg border-2 border-dashed p-2 transition-colors ${
                externalDrop ? 'border-app-accent bg-app-accentSoft' : 'border-slate-200 bg-slate-50'
              }`}
              onDragOver={(event) => {
                if (!event.dataTransfer.types.includes('Files')) return;
                event.preventDefault();
                setExternalDrop(true);
              }}
              onDragLeave={() => setExternalDrop(false)}
              onDrop={onExternalDrop}
            >
              {files.length === 0 ? (
                <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-3 text-center">
                  <p className="m-0 text-sm text-slate-600">파일을 여기로 끌어다 놓거나 “파일 추가”를 누르세요.</p>
                  <p className="m-0 text-xs text-slate-400">PDF · 이미지 · 한글(HWP, HWPX)</p>
                </div>
              ) : (
                <ol className="m-0 grid list-none gap-1.5 p-0">
                  {files.map((file, index) => {
                    const selected = selectedKeys.includes(file.key);
                    return (
                      <li
                        key={file.key}
                        draggable
                        onDragStart={(event) => {
                          event.dataTransfer.setData('text/plain', file.key);
                          event.dataTransfer.effectAllowed = 'move';
                          setDragKey(file.key);
                        }}
                        onDragEnd={() => {
                          setDragKey(null);
                          setDropKey(null);
                        }}
                        onDragOver={(event) => {
                          if (!dragKey) return;
                          event.preventDefault();
                          event.stopPropagation();
                          setDropKey(file.key);
                        }}
                        onDrop={(event) => {
                          if (!dragKey) return;
                          event.preventDefault();
                          event.stopPropagation();
                          moveFile(dragKey, file.key);
                          setDragKey(null);
                          setDropKey(null);
                        }}
                        onClick={(event) => onItemClick(event, file.key)}
                        className={`flex cursor-grab items-center gap-3 rounded-md border px-3 py-2 text-sm transition-colors active:cursor-grabbing ${
                          selected
                            ? 'border-app-accent bg-app-accentSoft text-slate-900'
                            : 'border-slate-200 bg-white text-slate-800 hover:bg-slate-50'
                        } ${dropKey === file.key && dragKey !== file.key ? 'border-t-2 border-t-app-accent' : ''}`}
                      >
                        <span className="w-6 shrink-0 text-right text-xs tabular-nums text-slate-400">{index + 1}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate" title={file.path}>
                            {baseName(file.path)}
                          </span>
                          <span className="block truncate text-[11px] text-slate-500">
                            {file.locked
                              ? '암호 보호 PDF'
                              : file.pages != null
                                ? `${file.pages}페이지`
                                : '페이지 수 확인 중…'}
                          </span>
                        </span>
                      </li>
                    );
                  })}
                </ol>
              )}
            </div>
          </section>

          <aside className="flex min-h-0 flex-col gap-4 overflow-auto">
            <label className="grid gap-1.5 text-sm text-slate-700">
              파일 이름
              <input
                className={fieldClass}
                value={outputName}
                placeholder="병합 파일 이름"
                onChange={(event) => setOutputName(event.target.value)}
              />
            </label>

            <div className="grid gap-1.5 text-sm text-slate-700">
              저장 위치
              <div className="flex gap-2">
                <input className={`${fieldClass} min-w-0 flex-1 text-xs`} value={outputFolder} readOnly title={outputFolder} />
                <button type="button" className={btnOutline} onClick={pickSaveFolder}>
                  찾아보기
                </button>
              </div>
            </div>

            <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-1.5 text-sm text-slate-700">
              미리 보기
              <div className="flex min-h-[220px] items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-slate-50 p-3">
                <PreviewBody
                  preview={preview}
                  passwordNeeded={passwordNeeded}
                  passwordInput={passwordInput}
                  onPasswordInput={setPasswordInput}
                  onSubmitPassword={submitPassword}
                  hasFile={Boolean(currentFile)}
                />
              </div>
            </div>
          </aside>
        </div>

        {error ? <p className="m-0 border-t border-red-100 bg-red-50 px-6 py-2 text-sm text-red-700">{error}</p> : null}

        <footer className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 px-6 py-3">
          <div className="mr-auto flex min-w-0 items-center gap-3">
            <p className="m-0 truncate text-[11px] text-slate-500">목록에서 파일을 위·아래로 끌면 병합 순서가 바뀝니다.</p>
            {busy ? <span className="shrink-0 text-sm text-slate-500">{busy}</span> : null}
          </div>
          <button type="button" className={btnGhost} onClick={onClose} disabled={Boolean(busy)}>
            취소
          </button>
          <button type="button" className={btnPrimary} onClick={() => void runMerge()} disabled={!files.length || Boolean(busy)}>
            병합
          </button>
        </footer>
      </div>
    </div>
  );
}

function PreviewBody({ preview, passwordNeeded, passwordInput, onPasswordInput, onSubmitPassword, hasFile }) {
  if (!hasFile) return <p className="m-0 text-sm text-slate-400">선택된 파일이 없습니다.</p>;
  if (!preview || preview.status === 'loading') return <p className="m-0 text-sm text-slate-400">미리 보는 중…</p>;
  if (preview.status === 'ok') {
    return (
      <div className="flex h-full w-full flex-col items-center gap-2">
        <img src={preview.src} alt="첫 쪽 미리보기" className="max-h-[260px] max-w-full bg-white object-contain shadow-sm" />
        <span className="text-xs text-slate-500">첫 쪽 · 전체 {preview.pageCount}페이지</span>
      </div>
    );
  }
  if (preview.status === 'unsupported') {
    return <p className="m-0 text-center text-sm text-slate-500">미리 보기를 만들 수 없습니다. 병합 시 한글 문서는 PDF로 변환됩니다.</p>;
  }
  if (preview.status === 'needsPassword' || passwordNeeded) {
    return (
      <form onSubmit={onSubmitPassword} className="grid w-full gap-2 text-center">
        <p className="m-0 text-sm text-slate-700">
          {preview.rejected ? '비밀번호가 올바르지 않습니다.' : '이 PDF는 비밀번호가 필요합니다.'}
        </p>
        <input
          type="password"
          value={passwordInput}
          onChange={(event) => onPasswordInput(event.target.value)}
          placeholder="비밀번호"
          autoFocus
          className={fieldClass}
        />
        <button type="submit" disabled={!passwordInput} className={btnPrimary}>
          확인
        </button>
      </form>
    );
  }
  return <p className="m-0 text-center text-sm text-red-600">{preview.message || '미리 보기를 만들지 못했습니다.'}</p>;
}
