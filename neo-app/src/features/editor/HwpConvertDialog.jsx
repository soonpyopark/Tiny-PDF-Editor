import { useEffect, useRef, useState } from 'react';
import { useDialog } from '../../context/DialogContext.jsx';
import { api } from '../../lib/apiClient.js';

/**
 * 한글(HWP, HWPX) → PDF 대화상자 (Tiny hwp_to_pdf_dialog.py 를 옮긴 것).
 * - 파일 추가 / 폴더에서 추가 / 끌어다 놓기, 목록에서 선택 후 제거
 * - 저장 위치: 원본과 같은 폴더 또는 지정 폴더 (지정 폴더는 기억)
 * - 파일 하나씩 변환하며 진행을 보여 주고, 중지를 누르면 다음 파일부터 멈춘다
 * - 같은 이름이 있으면 기본적으로 "이름 (2).pdf"로 저장, 덮어쓰기 선택 가능
 * - 변환 후 PDF 열기를 켜면 첫 번째 결과를 연다
 *
 * @param {{
 *   open: boolean,
 *   onClose: () => void,
 *   onConverted: (openPath: string | null) => void,
 * }} props
 */

const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'flex max-h-[min(640px,calc(100vh-48px))] w-full max-w-[640px] flex-col overflow-hidden rounded-xl bg-white shadow-xl';
const btnBase = 'inline-flex h-9 items-center justify-center rounded-full px-4 text-sm font-medium transition-colors disabled:cursor-default disabled:opacity-50';
const btnPrimary = `${btnBase} bg-app-accent px-6 text-white hover:bg-app-accentHover disabled:hover:bg-app-accent`;
const btnGhost = `${btnBase} text-slate-700 hover:bg-slate-100`;
const btnOutline = `${btnBase} border border-app-accentBorder text-app-accentText hover:bg-app-accentSoft`;
const TITLE = '한글(HWP, HWPX) → PDF';
const NOT_INSTALLED =
  '한컴 한글(한컴오피스)이 설치되어 있지 않습니다.\n\nHWP/HWPX 파일을 PDF로 변환하려면 한컴 한글이 필요합니다.';

function baseName(filePath) {
  return filePath.split(/[\\/]/).pop() || filePath;
}

function isHwpFile(filePath) {
  return /\.(hwp|hwpx)$/i.test(filePath || '');
}

export default function HwpConvertDialog({ open, onClose, onConverted }) {
  const dialog = useDialog();
  const [files, setFiles] = useState(/** @type {{ key: string, path: string }[]} */ ([]));
  const [selectedKeys, setSelectedKeys] = useState(/** @type {string[]} */ ([]));
  const [anchorKey, setAnchorKey] = useState(/** @type {string | null} */ (null));
  const [state, setState] = useState(/** @type {null | { windows: boolean, installed: boolean }} */ (null));
  const [besideSource, setBesideSource] = useState(true);
  const [saveFolder, setSaveFolder] = useState('');
  const [overwrite, setOverwrite] = useState(false);
  const [openAfter, setOpenAfter] = useState(false);
  const [progress, setProgress] = useState(/** @type {null | { index: number, total: number, name: string }} */ (null));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [externalDrop, setExternalDrop] = useState(false);
  const keySeq = useRef(0);
  const cancelRef = useRef(false);

  // 열 때마다 초기화하고, 저장한 설정(저장 위치)을 불러온다.
  useEffect(() => {
    if (!open) return;
    setFiles([]);
    setSelectedKeys([]);
    setAnchorKey(null);
    setOverwrite(false);
    setOpenAfter(false);
    setProgress(null);
    setBusy(false);
    setError('');
    cancelRef.current = false;
    api('pdf.hwpState')
      .then((result) => {
        setState({ windows: result.windows, installed: result.installed });
        setBesideSource(Boolean(result.besideSource));
        setSaveFolder(result.saveFolder || '');
      })
      .catch((err) => setError(err.message || '설정을 읽지 못했습니다.'));
  }, [open]);

  if (!open) return null;

  function addPaths(paths) {
    setError('');
    const seen = new Set(files.map((file) => file.path.toLowerCase()));
    const fresh = [...new Set(paths)].filter((item) => {
      if (!item || !isHwpFile(item)) return false;
      const key = item.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    if (!fresh.length) return;
    const created = fresh.map((path) => ({ key: `h${++keySeq.current}`, path }));
    setFiles((prev) => [...prev, ...created]);
    setAnchorKey(created[0].key);
    setSelectedKeys([created[0].key]);
  }

  async function pickFiles() {
    setError('');
    try {
      const result = await api('pdf.hwpPickFiles');
      if (result.canceled) return;
      addPaths(result.paths);
    } catch (err) {
      setError(err.message || '파일을 고르지 못했습니다.');
    }
  }

  async function pickFolder() {
    setError('');
    try {
      const result = await api('pdf.hwpPickFolder');
      if (result.canceled) return;
      if (!result.paths.length) {
        void dialog.alert({ title: TITLE, body: '선택한 폴더에 HWP/HWPX 파일이 없습니다.' });
        return;
      }
      addPaths(result.paths);
    } catch (err) {
      setError(err.message || '폴더를 읽지 못했습니다.');
    }
  }

  async function pickSaveFolder() {
    try {
      const result = await api('pdf.hwpPickSaveFolder');
      if (result.canceled) return;
      setSaveFolder(result.folder);
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

  // 목록 클릭: Shift 범위 선택, Ctrl 토글 선택 (병합 대화상자와 같은 방식).
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
    addPaths(paths);
  }

  async function runConvert() {
    if (busy || !files.length) return;
    if (state && !state.windows) {
      void dialog.alert({ title: TITLE, body: 'HWP/HWPX 변환은 Windows에서만 지원됩니다.' });
      return;
    }
    if (state && !state.installed) {
      void dialog.alert({ title: TITLE, body: NOT_INSTALLED });
      return;
    }
    if (!besideSource && !saveFolder) {
      void dialog.alert({ title: TITLE, body: '유효한 저장 폴더를 지정해 주세요.' });
      return;
    }

    setError('');
    cancelRef.current = false;
    setBusy(true);
    const converted = [];
    const failed = [];
    for (let index = 0; index < files.length; index += 1) {
      if (cancelRef.current) break;
      const name = baseName(files[index].path);
      setProgress({ index: index + 1, total: files.length, name });
      try {
        const result = await api('pdf.hwpConvertOne', {
          source: files[index].path,
          besideSource,
          folder: saveFolder,
          overwrite,
        });
        converted.push(result.path);
      } catch (err) {
        failed.push({ name, message: err.message || '변환하지 못했습니다.' });
      }
    }
    setProgress(null);
    setBusy(false);
    if (!converted.length && !failed.length) return;

    const details = failed.map((item) => `• ${item.name}: ${item.message}`).join('\n');
    if (!converted.length) {
      void dialog.alert({ title: TITLE, body: `변환에 실패했습니다.\n\n${details}` });
      return;
    }
    if (!failed.length) {
      void dialog.alert({ title: TITLE, body: `${converted.length}개 파일을 PDF로 변환했습니다.` });
    } else {
      void dialog.alert({ title: TITLE, body: `${converted.length}개 변환, ${failed.length}개 실패.\n\n${details}` });
    }
    // 원본처럼 열기는 첫 번째 결과만 연다. 나머지는 저장 폴더에 있다.
    onConverted(openAfter ? converted[0] : null);
  }

  const installIssue = state && !state.windows ? 'HWP/HWPX 변환은 Windows에서만 지원됩니다.' : state && !state.installed ? NOT_INSTALLED : '';

  return (
    <div className={overlayClass} role="presentation" onClick={busy ? undefined : onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="hwp-convert-title"
        className={cardClass}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !busy) onClose();
        }}
      >
        <header className="flex items-center gap-3 border-b border-slate-200 px-6 py-4">
          <div className="min-w-0 flex-1">
            <h2 id="hwp-convert-title" className="m-0 text-lg font-semibold text-slate-900">
              {TITLE}
            </h2>
            <p className="m-0 mt-0.5 text-xs text-slate-500">
              각 HWP/HWPX 파일을 개별 PDF로 저장합니다. Windows에서 한컴 한글이 필요합니다.
            </p>
          </div>
          <button type="button" className={btnGhost} onClick={onClose} disabled={busy}>
            닫기
          </button>
        </header>

        {installIssue ? (
          <p className="m-0 whitespace-pre-line border-b border-amber-100 bg-amber-50 px-6 py-2 text-sm text-amber-800">
            {installIssue}
          </p>
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto px-6 py-5">
          <div className="flex items-center gap-2">
            <button type="button" className={btnOutline} disabled={!selectedKeys.length || busy} onClick={removeSelected}>
              선택 제거
            </button>
            <button type="button" className={btnOutline} disabled={busy} onClick={pickFolder}>
              폴더에서 추가
            </button>
            <button type="button" className={btnPrimary} disabled={busy} onClick={pickFiles}>
              파일 추가
            </button>
            <span className="ml-auto text-xs text-slate-500">{files.length ? `${files.length}개 파일` : ''}</span>
          </div>

          <div
            className={`min-h-[180px] flex-1 overflow-auto rounded-lg border-2 border-dashed p-2 transition-colors ${
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
              <div className="flex h-full min-h-[160px] flex-col items-center justify-center gap-2 text-center">
                <p className="m-0 text-sm text-slate-600">한글 파일을 여기로 끌어다 놓거나 “파일 추가”를 누르세요.</p>
                <p className="m-0 text-xs text-slate-400">.hwp · .hwpx</p>
              </div>
            ) : (
              <ul className="m-0 grid list-none gap-1.5 p-0">
                {files.map((file) => {
                  const selected = selectedKeys.includes(file.key);
                  return (
                    <li
                      key={file.key}
                      onClick={(event) => onItemClick(event, file.key)}
                      className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm transition-colors ${
                        selected
                          ? 'border-app-accent bg-app-accentSoft text-slate-900'
                          : 'border-slate-200 bg-white text-slate-800 hover:bg-slate-50'
                      }`}
                    >
                      <span className="min-w-0 flex-1 truncate" title={file.path}>
                        {baseName(file.path)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <p className="m-0 text-[11px] text-slate-500">한글 파일을 끌어다 놓거나 추가할 수 있습니다.</p>

          <div className="grid gap-2 text-sm text-slate-700">
            <span className="font-semibold">저장 위치</span>
            <label className="flex items-center gap-2">
              <input type="radio" name="hwp-save-where" checked={besideSource} onChange={() => setBesideSource(true)} />
              원본과 같은 폴더
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="hwp-save-where" checked={!besideSource} onChange={() => setBesideSource(false)} />
              지정 폴더
            </label>
            <div className="flex gap-2">
              <input
                className="h-9 min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-2.5 text-xs text-slate-800 outline-none disabled:bg-slate-100"
                value={saveFolder}
                readOnly
                disabled={besideSource}
                title={saveFolder}
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
        </div>

        {error ? <p className="m-0 border-t border-red-100 bg-red-50 px-6 py-2 text-sm text-red-700">{error}</p> : null}

        <footer className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 px-6 py-3">
          <div className="mr-auto min-w-0 truncate text-sm text-slate-500">
            {progress ? `${progress.index}/${progress.total} 변환 중… ${progress.name}` : ''}
          </div>
          {busy ? (
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
            <button type="button" className={btnGhost} onClick={onClose}>
              취소
            </button>
          )}
          <button type="button" className={btnPrimary} onClick={() => void runConvert()} disabled={!files.length || busy}>
            변환
          </button>
        </footer>
      </div>
    </div>
  );
}
