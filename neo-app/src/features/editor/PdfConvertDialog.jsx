import { useEffect, useRef, useState } from 'react';
import { useDialog } from '../../context/DialogContext.jsx';
import { api } from '../../lib/apiClient.js';
import { useAnchoredPlacement } from '../../lib/menuPlacement.js';

/**
 * PDF 변환 대화상자 — 예전 "PDF 병합"(Tiny merge_pdf_dialog.py)과
 * "한글(HWP, HWPX) → PDF"(Tiny hwp_to_pdf_dialog.py)를 하나로 합친 것.
 *
 * 공통: 파일 추가 / 폴더에서 추가 / 끌어다 놓기, 선택 제거, 목록 순서, 첫 쪽 미리보기.
 * 파일 형식: PDF · 이미지 · 한글(HWP, HWPX).
 *
 * 모드 (위쪽에서 고른다):
 *  - 병합: 목록 순서대로 PDF 하나로 합친다. 파일 이름·저장 폴더를 정하고, 같은 이름이 있으면 덮어쓰기를 확인한다.
 *          암호 PDF 는 해당 파일에서 바로 비밀번호를 받는다. 끝나면 저장한 파일을 연다.
 *  - 개별 변환: 이미지·한글 파일을 각각 PDF 로 저장한다 (이미 PDF 인 파일은 제외).
 *          원본과 같은 폴더 또는 지정 폴더, 덮어쓰기(기본은 "이름 (2).pdf"), 변환 후 열기.
 *          파일 하나씩 변환하며 진행을 보여 주고, 중지는 다음 파일부터 멈춘다.
 *
 * 기본 모드: 파일이 1개면 개별 변환(1개를 병합할 일은 거의 없다), 2개 이상이면 마지막에 쓴 모드.
 * 한컴 한글 설치 확인은 한글 파일이 목록에 들어왔을 때만 한다 (엔진을 띄워야 하므로).
 */

const TITLE = 'PDF로 변환하기';
const MODE_KEY = 'tinypdfneo.convertMode';
const DEFAULT_NAME = '병합';
const NOT_INSTALLED =
  '한컴 한글(한컴오피스)이 설치되어 있지 않습니다.\n\nHWP/HWPX 파일을 PDF로 변환하려면 한컴 한글이 필요합니다.';
const NOT_WINDOWS = 'HWP/HWPX 변환은 Windows에서만 지원됩니다.';

const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'flex h-[min(640px,calc(100vh-48px))] w-full max-w-[920px] flex-col overflow-hidden rounded-xl bg-white shadow-xl';
const fieldClass =
  'h-9 w-full rounded-md border border-slate-300 bg-white px-2.5 text-sm text-slate-800 outline-none focus:border-app-accent disabled:bg-slate-100';
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

/** @returns {'pdf' | 'hwp' | 'image'} */
function kindOf(filePath) {
  const ext = (/\.([^.\\/]+)$/.exec(filePath || '')?.[1] || '').toLowerCase();
  if (ext === 'pdf') return 'pdf';
  if (ext === 'hwp' || ext === 'hwpx') return 'hwp';
  return 'image';
}

function readSavedMode() {
  try {
    return window.localStorage.getItem(MODE_KEY) === 'each' ? 'each' : 'merge';
  } catch {
    return 'merge';
  }
}

function saveMode(mode) {
  try {
    window.localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* 저장하지 못해도 이번 대화상자에서는 그대로 쓴다 */
  }
}

/**
 * @param {{
 *   open: boolean,
 *   onClose: () => void,
 *   onDone: (openPath: string | null) => void,
 * }} props
 */
/** "파일 추가" 단추 아래 메뉴. 대화상자 가장자리에 걸려도 화면 안에 맞춘다. */
function AddFilesMenu({ children }) {
  const ref = useRef(null);
  useAnchoredPlacement(ref, { gap: 4 });
  return (
    <div ref={ref} role="menu" className="fixed left-0 top-0 z-10 w-44 rounded-md border border-slate-200 bg-white py-1 shadow-lg">
      {children}
    </div>
  );
}

export default function PdfConvertDialog({ open, onClose, onDone }) {
  const dialog = useDialog();
  const [mode, setMode] = useState(/** @type {'merge' | 'each'} */ ('merge'));
  const [files, setFiles] = useState(/** @type {{ key: string, path: string, pages: number | null, locked: boolean }[]} */ ([]));
  const [selectedKeys, setSelectedKeys] = useState(/** @type {string[]} */ ([]));
  const [anchorKey, setAnchorKey] = useState(/** @type {string | null} */ (null));
  const [outputName, setOutputName] = useState(DEFAULT_NAME);
  const [outputFolder, setOutputFolder] = useState('');
  const [besideSource, setBesideSource] = useState(true);
  const [overwrite, setOverwrite] = useState(false);
  const [openAfter, setOpenAfter] = useState(false);
  const [windows, setWindows] = useState(true);
  const [hwpInfo, setHwpInfo] = useState(/** @type {null | { windows: boolean, installed: boolean }} */ (null));
  const [results, setResults] = useState(/** @type {Record<string, { status: 'running' | 'done' | 'failed', text?: string }>} */ ({}));
  const [progress, setProgress] = useState(/** @type {null | { index: number, total: number, name: string }} */ (null));
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
  const cancelRef = useRef(false);
  const modeChosen = useRef(false);

  const currentFile = files.find((file) => file.key === anchorKey) ?? files[0] ?? null;
  const currentPath = currentFile?.path ?? '';
  const currentPassword = passwords[currentPath] ?? '';
  const hasHwp = files.some((file) => kindOf(file.path) === 'hwp');

  // 열 때마다 초기화하고, 저장해 둔 설정(저장 위치·모드)을 불러온다.
  useEffect(() => {
    if (!open) return;
    setFiles([]);
    setSelectedKeys([]);
    setAnchorKey(null);
    setOutputName(DEFAULT_NAME);
    setOverwrite(false);
    setOpenAfter(false);
    setResults({});
    setProgress(null);
    setPasswords({});
    setPasswordFor(null);
    setPasswordInput('');
    setPreview(null);
    setBusy('');
    setError('');
    setMenuOpen(false);
    setHwpInfo(null);
    cancelRef.current = false;
    modeChosen.current = false;
    setMode(readSavedMode());
    api('pdf.convertState')
      .then((state) => {
        setOutputFolder(state.saveFolder || '');
        setBesideSource(Boolean(state.besideSource));
        setWindows(Boolean(state.windows));
      })
      .catch(() => setOutputFolder(''));
  }, [open]);

  // 사용자가 모드를 직접 고르기 전에는 파일 수에 맞춘다: 1개 → 개별 변환, 그 밖에는 마지막에 쓴 모드.
  useEffect(() => {
    if (!open || modeChosen.current) return;
    setMode(files.length === 1 ? 'each' : readSavedMode());
  }, [open, files.length]);

  // 한글 파일이 처음 들어왔을 때만 한컴 한글 설치 여부를 확인한다.
  useEffect(() => {
    if (!open || !hasHwp || hwpInfo) return;
    api('pdf.hwpAvailable')
      .then((info) => setHwpInfo({ windows: Boolean(info.windows), installed: Boolean(info.installed) }))
      .catch(() => setHwpInfo({ windows: true, installed: false }));
  }, [open, hasHwp, hwpInfo]);

  // 현재 파일의 첫 쪽 미리보기 (비밀번호가 바뀌면 다시).
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

  /** 한글 변환이 안 되는 이유 (되면 빈 문자열). 아직 모르면 지금 확인한다. */
  async function hwpIssue() {
    let info = hwpInfo;
    if (!info) {
      try {
        const result = await api('pdf.hwpAvailable');
        info = { windows: Boolean(result.windows), installed: Boolean(result.installed) };
      } catch {
        info = { windows: true, installed: false };
      }
      setHwpInfo(info);
    }
    if (!info.windows) return NOT_WINDOWS;
    if (!info.installed) return NOT_INSTALLED;
    return '';
  }

  const knownHwpIssue = hasHwp ? (!windows ? NOT_WINDOWS : hwpInfo && !hwpInfo.installed ? NOT_INSTALLED : '') : '';

  function chooseMode(next) {
    if (busy) return;
    modeChosen.current = true;
    saveMode(next);
    setMode(next);
    setError('');
  }

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
          title: TITLE,
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
      setBesideSource(false);
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

  /* ---- 병합 ---- */

  async function runMerge({ overwrite: replace = false } = {}) {
    if (!files.length || busy) return;
    setError('');
    if (hasHwp) {
      const issue = await hwpIssue();
      if (issue) {
        void dialog.alert({ title: TITLE, body: issue });
        return;
      }
    }
    setBusy('병합하는 중…');
    try {
      const result = await api('pdf.mergeRun', {
        paths: files.map((file) => file.path),
        name: outputName,
        folder: outputFolder,
        passwords,
        overwrite: replace,
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
          title: TITLE,
          body: `같은 이름의 파일이 있습니다.\n덮어쓰시겠습니까?\n\n${result.target}`,
          confirmLabel: '덮어쓰기',
          confirmVariant: 'danger',
        });
        if (ok) await runMerge({ overwrite: true });
        return;
      }
      onDone(result.path);
    } catch (err) {
      setBusy('');
      setError(err.message || '병합하지 못했습니다.');
    }
  }

  /* ---- 개별 변환 ---- */

  const convertible = files.filter((file) => kindOf(file.path) !== 'pdf');
  const skippedPdf = files.length - convertible.length;

  async function runConvert() {
    if (busy || !convertible.length) return;
    if (!besideSource && !outputFolder) {
      void dialog.alert({ title: TITLE, body: '유효한 저장 폴더를 지정해 주세요.' });
      return;
    }
    setError('');
    const issue = convertible.some((file) => kindOf(file.path) === 'hwp') ? await hwpIssue() : '';

    cancelRef.current = false;
    setBusy('변환하는 중…');
    setResults({});
    const converted = [];
    const failed = [];
    for (let index = 0; index < convertible.length; index += 1) {
      if (cancelRef.current) break;
      const file = convertible[index];
      const name = baseName(file.path);
      setProgress({ index: index + 1, total: convertible.length, name });
      if (kindOf(file.path) === 'hwp' && issue) {
        failed.push({ name, message: issue.split('\n')[0] });
        setResults((prev) => ({ ...prev, [file.key]: { status: 'failed', text: issue.split('\n')[0] } }));
        continue;
      }
      setResults((prev) => ({ ...prev, [file.key]: { status: 'running' } }));
      try {
        const result = await api('pdf.convertOne', {
          source: file.path,
          besideSource,
          folder: outputFolder,
          overwrite,
        });
        converted.push(result.path);
        setResults((prev) => ({ ...prev, [file.key]: { status: 'done', text: baseName(result.path) } }));
      } catch (err) {
        const message = err.message || '변환하지 못했습니다.';
        failed.push({ name, message });
        setResults((prev) => ({ ...prev, [file.key]: { status: 'failed', text: message } }));
      }
    }
    setProgress(null);
    setBusy('');
    if (!converted.length && !failed.length) return;

    const details = failed.map((item) => `• ${item.name}: ${item.message}`).join('\n');
    const skipNote = skippedPdf ? `\n\n이미 PDF인 ${skippedPdf}개 파일은 변환하지 않았습니다.` : '';
    if (!converted.length) {
      void dialog.alert({ title: TITLE, body: `변환에 실패했습니다.\n\n${details}` });
      return;
    }
    if (!failed.length) {
      void dialog.alert({ title: TITLE, body: `${converted.length}개 파일을 PDF로 변환했습니다.${skipNote}` });
    } else {
      void dialog.alert({
        title: TITLE,
        body: `${converted.length}개 변환, ${failed.length}개 실패.\n\n${details}${skipNote}`,
      });
    }
    // 원본처럼 열기는 첫 번째 결과만 연다. 나머지는 저장 위치에 있다.
    onDone(openAfter ? converted[0] : null);
  }

  const isMerge = mode === 'merge';
  const running = Boolean(busy);
  const passwordNeeded = passwordFor && currentPath === passwordFor.path;
  const pageTotal = files.reduce((sum, file) => sum + (file.pages ?? 0), 0);

  function rowNote(file) {
    const kind = kindOf(file.path);
    const result = results[file.key];
    if (!isMerge && result) {
      if (result.status === 'running') return { text: '변환 중…', tone: 'text-slate-500' };
      if (result.status === 'done') return { text: `완료 → ${result.text}`, tone: 'text-emerald-700' };
      return { text: `실패: ${result.text}`, tone: 'text-red-600' };
    }
    if (isMerge) {
      if (file.locked) return { text: '암호 보호 PDF', tone: 'text-slate-500' };
      if (kind === 'hwp') return { text: '한글 문서 · 병합할 때 PDF로 변환', tone: 'text-slate-500' };
      return { text: file.pages != null ? `${file.pages}페이지` : '페이지 수 확인 중…', tone: 'text-slate-500' };
    }
    if (kind === 'pdf') return { text: '이미 PDF · 변환에서 제외', tone: 'text-slate-400' };
    if (kind === 'hwp') return { text: '한글 문서 → PDF', tone: 'text-slate-500' };
    return { text: '이미지 → PDF', tone: 'text-slate-500' };
  }

  return (
    <div className={overlayClass} role="presentation" onClick={running ? undefined : onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="pdf-convert-title"
        className={cardClass}
        onClick={(event) => {
          event.stopPropagation();
          setMenuOpen(false);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !running) onClose();
          const onControl =
            event.target instanceof HTMLInputElement ||
            event.target instanceof HTMLButtonElement ||
            event.target instanceof HTMLSelectElement;
          if (event.key === 'Enter' && !onControl) {
            event.preventDefault();
            void (isMerge ? runMerge() : runConvert());
          }
        }}
      >
        <header className="flex items-center gap-3 border-b border-slate-200 px-6 py-4">
          <div className="min-w-0 flex-1">
            <h2 id="pdf-convert-title" className="m-0 text-lg font-semibold text-slate-900">
              {TITLE}
            </h2>
            <p className="m-0 mt-0.5 text-xs text-slate-500">
              {isMerge
                ? '목록 순서대로 PDF 하나로 합칩니다. 끌어서 순서를 바꾸거나 파일을 끌어다 놓을 수 있습니다.'
                : '이미지·한글 파일을 각각 PDF로 저장합니다. 이미 PDF인 파일은 제외됩니다.'}
            </p>
          </div>
          <div
            role="radiogroup"
            aria-label="변환 방식"
            className="inline-flex gap-1 rounded-full border border-slate-200 bg-slate-50 p-0.5"
          >
            {[
              { id: 'merge', label: '하나의 PDF로 병합' },
              { id: 'each', label: '개별 변환' },
            ].map((item) => (
              <button
                key={item.id}
                type="button"
                role="radio"
                aria-checked={mode === item.id}
                disabled={running}
                onClick={() => chooseMode(item.id)}
                className={`inline-flex h-8 items-center rounded-full px-4 text-sm font-medium transition-colors disabled:cursor-default ${
                  mode === item.id ? 'bg-app-accent text-white' : 'text-slate-700 hover:bg-slate-200 disabled:hover:bg-transparent'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button type="button" className={btnGhost} onClick={onClose} disabled={running}>
            닫기
          </button>
        </header>

        {knownHwpIssue ? (
          <p className="m-0 whitespace-pre-line border-b border-amber-100 bg-amber-50 px-6 py-2 text-sm text-amber-800">
            {knownHwpIssue}
          </p>
        ) : null}

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_280px] gap-5 px-6 py-5">
          <section className="flex min-h-0 flex-col gap-3">
            <div className="flex items-center gap-2">
              <div className="relative">
                <button
                  type="button"
                  className={btnPrimary}
                  disabled={running}
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
                  <AddFilesMenu>
                    <button type="button" role="menuitem" className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-100" onClick={pickFiles}>
                      파일 추가...
                    </button>
                    <button type="button" role="menuitem" className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-100" onClick={pickFolder}>
                      폴더에서 추가...
                    </button>
                  </AddFilesMenu>
                ) : null}
              </div>
              <button type="button" className={btnOutline} disabled={!selectedKeys.length || running} onClick={removeSelected}>
                선택 제거
              </button>
              <span className="ml-auto text-xs text-slate-500">
                {files.length
                  ? isMerge
                    ? `${files.length}개 파일 · ${pageTotal}페이지`
                    : `${files.length}개 파일 · 변환 대상 ${convertible.length}개`
                  : ''}
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
                    const note = rowNote(file);
                    const excluded = !isMerge && kindOf(file.path) === 'pdf';
                    return (
                      <li
                        key={file.key}
                        draggable={!running}
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
                        } ${excluded ? 'opacity-60' : ''} ${dropKey === file.key && dragKey !== file.key ? 'border-t-2 border-t-app-accent' : ''}`}
                      >
                        <span className="w-6 shrink-0 text-right text-xs tabular-nums text-slate-400">{index + 1}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate" title={file.path}>
                            {baseName(file.path)}
                          </span>
                          <span className={`block truncate text-[11px] ${note.tone}`} title={note.text}>
                            {note.text}
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
            {isMerge ? (
              <>
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
              </>
            ) : (
              <>
                <div className="grid gap-2 text-sm text-slate-700">
                  <span className="font-semibold">저장 위치</span>
                  <label className="flex items-center gap-2">
                    <input type="radio" name="convert-save-where" checked={besideSource} onChange={() => setBesideSource(true)} />
                    원본과 같은 폴더
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="radio" name="convert-save-where" checked={!besideSource} onChange={() => setBesideSource(false)} />
                    지정 폴더
                  </label>
                  <div className="flex gap-2">
                    <input
                      className={`${fieldClass} min-w-0 flex-1 text-xs`}
                      value={outputFolder}
                      readOnly
                      disabled={besideSource}
                      title={outputFolder}
                    />
                    <button type="button" className={btnOutline} disabled={besideSource} onClick={pickSaveFolder}>
                      찾아보기
                    </button>
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} />
                  같은 이름의 PDF가 있으면 덮어쓰기
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={openAfter} onChange={(event) => setOpenAfter(event.target.checked)} />
                  변환 후 PDF 열기
                </label>
              </>
            )}

            <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-1.5 text-sm text-slate-700">
              미리 보기
              <div className="flex min-h-[180px] items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-slate-50 p-3">
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
            {progress ? (
              <span className="min-w-0 truncate text-sm text-slate-500">
                {progress.index}/{progress.total} 변환 중… {progress.name}
              </span>
            ) : running ? (
              <span className="shrink-0 text-sm text-slate-500">{busy}</span>
            ) : (
              <p className="m-0 truncate text-[11px] text-slate-500">
                {isMerge
                  ? '목록에서 파일을 위·아래로 끌면 병합 순서가 바뀝니다.'
                  : files.length && !convertible.length
                    ? '변환할 이미지나 한글 파일이 없습니다. 이미 PDF인 파일을 합치려면 “하나의 PDF로 병합”을 고르세요.'
                    : '파일을 하나씩 변환합니다. 중지하면 다음 파일부터 멈춥니다.'}
              </p>
            )}
          </div>
          {progress ? (
            <button
              type="button"
              className={btnGhost}
              onClick={() => {
                cancelRef.current = true;
              }}
            >
              중지
            </button>
          ) : (
            <button type="button" className={btnGhost} onClick={onClose} disabled={running}>
              취소
            </button>
          )}
          {isMerge ? (
            <button type="button" className={btnPrimary} onClick={() => void runMerge()} disabled={!files.length || running}>
              병합
            </button>
          ) : (
            <button type="button" className={btnPrimary} onClick={() => void runConvert()} disabled={!convertible.length || running}>
              변환
            </button>
          )}
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
    return <p className="m-0 text-center text-sm text-slate-500">한글 문서는 미리 볼 수 없습니다. PDF로 변환하면 내용을 볼 수 있습니다.</p>;
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
