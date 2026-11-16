import { useEffect, useMemo, useRef, useState } from 'react';
import { useDialog } from '../../context/DialogContext.jsx';
import { api } from '../../lib/apiClient.js';

/**
 * 개인정보 제거 대화상자 (Tiny pii_remove_dialog.py PiiRemoveDialog 를 옮긴 것).
 * - 열 때 자동 검사 (페이지 범위가 있으면 그 쪽만), 다시 검사 가능
 * - 목록: 선택 · 페이지 · 유형 · 내용 · 위치. 위치가 확인된 항목만 제거 대상
 * - 유형 필터 / 이 유형만 선택 / 모두 선택 / 모두 해제 / 표시 방식
 * - 행을 누르면 그 항목 위치를 미리보기 (빨간 상자) 로 보여준다
 * - 제거 전 확인 후 원본 텍스트를 레닥션한다 (실행 취소 가능)
 */

const REDACT_STYLE_CHOICES = [
  { id: 'gray', label: '회색 박스' },
  { id: 'black', label: '검정 박스' },
  { id: 'light_blue', label: '연한 파랑 박스' },
  { id: 'light_red', label: '연한 빨강 박스' },
  { id: 'label', label: '한글 라벨' },
];
const DEFAULT_STYLE = 'black';

const overlayClass = 'fixed inset-0 z-[2000] flex items-center justify-center bg-[rgba(32,33,36,0.4)] p-4';
const cardClass = 'flex h-[min(600px,calc(100vh-48px))] w-full max-w-[920px] flex-col overflow-hidden rounded-xl bg-white shadow-xl';
const selectClass =
  'h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-800 outline-none focus:border-app-accent disabled:opacity-50';
const btnBase = 'inline-flex h-8 items-center justify-center rounded-full px-3.5 text-sm font-medium transition-colors disabled:cursor-default disabled:opacity-50';
const btnOutline = `${btnBase} border border-app-accentBorder text-app-accentText hover:bg-app-accentSoft disabled:hover:bg-transparent`;
const btnGhost = `${btnBase} text-slate-700 hover:bg-slate-100`;
const btnPrimary = `${btnBase} h-9 bg-app-accent px-6 text-white hover:bg-app-accentHover disabled:hover:bg-app-accent`;

/** Matches pdf_editor.pii_remove.format_pii_scope. */
function scopeLabel(pageIndices) {
  if (!Array.isArray(pageIndices)) return '전체 페이지';
  const unique = [...new Set(pageIndices)];
  if (!unique.length) return '선택한 페이지';
  if (unique.length === 1) return `${unique[0] + 1}페이지`;
  return `선택한 ${unique.length}개 페이지`;
}

/** Matches pdf_editor.pii_remove.format_pii_count. */
function countText(hitCount, areaCount) {
  return `${hitCount}건(영역 ${areaCount}개)`;
}

function areaOf(hits) {
  return hits.reduce((sum, hit) => sum + (hit.hasGeometry ? hit.rects.length : 0), 0);
}

/**
 * @param {{
 *   open: boolean,
 *   pageIndices: number[] | null,
 *   onClose: () => void,
 *   onPreview: (hit: any, selected: any[]) => void,
 *   onApply: (hits: any[], style: string) => void,
 * }} props
 */
export default function PiiRemoveDialog({ open, pageIndices, onClose, onPreview, onApply }) {
  const dialog = useDialog();
  const [scanning, setScanning] = useState(false);
  const [status, setStatus] = useState('');
  const [hits, setHits] = useState(/** @type {any[]} */ ([]));
  const [checked, setChecked] = useState(/** @type {Set<number>} */ (new Set()));
  const [typeFilter, setTypeFilter] = useState('');
  const [styleId, setStyleId] = useState(DEFAULT_STYLE);
  const [onlyLocatable, setOnlyLocatable] = useState(true);
  const [summary, setSummary] = useState(/** @type {null | { pagesScanned: number, pagesWithoutText: number, locatableCount: number, areaCount: number }} */ (null));
  const scanToken = useRef(0);

  const scope = scopeLabel(pageIndices);
  const scopeKey = Array.isArray(pageIndices) ? pageIndices.join(',') : '';

  async function runScan(scopePages) {
    const token = ++scanToken.current;
    setScanning(true);
    setStatus('개인정보 검사 중…');
    setHits([]);
    setChecked(new Set());
    setSummary(null);
    try {
      const body = Array.isArray(scopePages) ? { pageIndices: scopePages } : {};
      const result = await api('pdf.piiScan', body);
      if (scanToken.current !== token) return;
      const list = Array.isArray(result.hits) ? result.hits : [];
      setHits(list);
      setChecked(new Set(list.flatMap((hit, index) => (hit.hasGeometry ? [index] : []))));
      setSummary({
        pagesScanned: result.pagesScanned ?? 0,
        pagesWithoutText: result.pagesWithoutText ?? 0,
        locatableCount: result.locatableCount ?? 0,
        areaCount: result.areaCount ?? 0,
      });
      setStatus(
        `검출 ${list.length}건 · 위치 확인 ${countText(result.locatableCount ?? 0, result.areaCount ?? 0)} · ` +
          `텍스트 없는 페이지 ${result.pagesWithoutText ?? 0} / ${result.pagesScanned ?? 0}`,
      );
    } catch (err) {
      if (scanToken.current !== token) return;
      setStatus('검사 실패');
      void dialog.alert({
        title: '개인정보 제거',
        body: err instanceof Error ? err.message : '개인정보를 검사하지 못했습니다.',
      });
    } finally {
      if (scanToken.current === token) setScanning(false);
    }
  }

  useEffect(() => {
    if (!open) return undefined;
    setStyleId(DEFAULT_STYLE);
    setTypeFilter('');
    setOnlyLocatable(true);
    void runScan(Array.isArray(pageIndices) ? pageIndices : null);
    return () => {
      // 닫히면 진행 중인 검사 결과는 버린다.
      scanToken.current += 1;
    };
    // 열릴 때 한 번만 검사한다 (범위가 바뀌면 열기 쪽에서 다시 연다).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scopeKey]);

  const labelCounts = useMemo(() => {
    const counts = new Map();
    for (const hit of hits) {
      const entry = counts.get(hit.label) ?? { label: hit.label, display: hit.labelDisplay || hit.label, count: 0 };
      entry.count += 1;
      counts.set(hit.label, entry);
    }
    return [...counts.values()].sort((a, b) => a.display.localeCompare(b.display, 'ko'));
  }, [hits]);

  if (!open) return null;

  const visibleRows = hits
    .map((hit, index) => ({ hit, index }))
    .filter(({ hit }) => !typeFilter || hit.label === typeFilter);

  function selectedFrom(set) {
    return hits.filter((hit, index) => set.has(index) && hit.hasGeometry);
  }

  const selectedCount = selectedFrom(checked).length;

  function rowClick(index) {
    const hit = hits[index];
    if (!hit) return;
    const next = new Set(checked);
    if (hit.hasGeometry) {
      if (next.has(index)) next.delete(index);
      else next.add(index);
      setChecked(next);
    }
    onPreview(hit, selectedFrom(next));
  }

  function setVisibleChecked(on) {
    const next = new Set(checked);
    for (const { hit, index } of visibleRows) {
      if (!hit.hasGeometry) continue;
      if (on) next.add(index);
      else next.delete(index);
    }
    setChecked(next);
  }

  function selectTypeOnly() {
    if (!typeFilter) return;
    const next = new Set();
    hits.forEach((hit, index) => {
      if (hit.hasGeometry && hit.label === typeFilter) next.add(index);
    });
    setChecked(next);
  }

  function recheckDefaults() {
    setChecked(new Set(hits.flatMap((hit, index) => (hit.hasGeometry ? [index] : []))));
  }

  async function accept() {
    if (scanning) return;
    const selected = selectedFrom(checked);
    if (!selected.length) {
      void dialog.alert({
        title: '개인정보 제거',
        body: '제거할 항목을 선택하세요.\n위치가 확인된 항목만 적용됩니다.',
      });
      return;
    }
    const ok = await dialog.confirm({
      title: '개인정보 제거',
      body:
        `선택한 ${countText(selected.length, areaOf(selected))}의 원본 내용을 문서에서 삭제합니다.\n` +
        '미리보기의 빨간 상자가 실제로 지워지는 범위입니다.\n' +
        '이 작업은 저장 전에도 문서에 바로 반영되며, 실행 취소로 되돌릴 수 있습니다.\n\n' +
        '계속할까요?',
      confirmVariant: 'danger',
    });
    if (!ok) return;
    onApply(selected, styleId);
  }

  const canApply = !scanning && hits.length > 0;

  return (
    <div className={overlayClass} role="dialog" aria-modal="true" aria-label={`개인정보 제거 — ${scope}`}>
      <div className={cardClass}>
        <div className="border-b border-slate-200 px-5 pb-3 pt-4">
          <h2 className="text-base font-semibold text-slate-900">
            {scope === '전체 페이지' ? '개인정보 제거' : `개인정보 제거 — ${scope}`}
          </h2>
          <p className="mt-1 text-sm font-medium text-slate-800">
            {scope === '전체 페이지'
              ? '문서에서 개인정보를 찾아 원본 내용을 제거합니다.'
              : `${scope}에서 개인정보를 찾아 원본 내용을 제거합니다.`}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            {'검은 박스로 덮는 방식이 아니라 PDF 원본 텍스트를 삭제하는 레닥션입니다. 자동 탐지는 완전하지 않으니 저장 전 결과를 확인하세요.'}
            <br />
            {'목록을 클릭하면 선택/해제되고, 미리보기의 빨간 상자가 실제로 지워지는 범위입니다.'}
            <br />
            {'텍스트 레이어가 없는 스캔 PDF는 탐지되지 않을 수 있습니다.'}
          </p>
        </div>

        <div className="px-5 pt-3">
          <p className="text-sm text-slate-800" role="status">
            {status}
          </p>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
            {scanning ? (
              <div className="h-full w-1/3 animate-pulse rounded-full bg-app-accent" />
            ) : (
              <div
                className="h-full rounded-full bg-app-accent transition-all"
                style={{ width: summary && summary.pagesScanned ? '100%' : '0%' }}
              />
            )}
          </div>
        </div>

        <div className="mt-3 min-h-0 flex-1 overflow-auto border-y border-slate-200">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs text-slate-600">
              <tr>
                <th className="w-12 px-2 py-2 font-medium">선택</th>
                <th className="w-16 px-2 py-2 font-medium">페이지</th>
                <th className="w-28 px-2 py-2 font-medium">유형</th>
                <th className="px-2 py-2 font-medium">내용</th>
                <th className="w-28 px-2 py-2 font-medium">위치</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map(({ hit, index }) => {
                const isChecked = checked.has(index);
                const preview = hit.text.length > 80 ? `${hit.text.slice(0, 77)}...` : hit.text;
                return (
                  <tr
                    key={`${hit.pageIndex}-${index}`}
                    onClick={() => rowClick(index)}
                    className={`cursor-pointer border-t border-slate-100 hover:bg-app-accentSoft ${
                      hit.hasGeometry ? '' : 'text-slate-400'
                    }`}
                  >
                    <td className="px-2 py-1.5">
                      <input
                        type="checkbox"
                        readOnly
                        disabled={!hit.hasGeometry}
                        checked={hit.hasGeometry && isChecked}
                        className="pointer-events-none h-4 w-4 accent-app-accent"
                        tabIndex={-1}
                        aria-label={`${hit.pageIndex + 1}페이지 ${hit.labelDisplay} 선택`}
                      />
                    </td>
                    <td className="px-2 py-1.5 text-center">{hit.pageIndex + 1}</td>
                    <td className="px-2 py-1.5">{hit.labelDisplay || hit.label}</td>
                    <td className="truncate px-2 py-1.5" title={hit.text}>
                      {preview}
                    </td>
                    <td className="px-2 py-1.5">{hit.hasGeometry ? '확인됨' : '위치 없음(제외)'}</td>
                  </tr>
                );
              })}
              {!scanning && !visibleRows.length ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-sm text-slate-400">
                    {hits.length ? '선택한 유형의 항목이 없습니다.' : '검출된 개인정보가 없습니다.'}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-2 px-5 py-3">
          <button type="button" className={btnOutline} disabled={scanning} onClick={() => runScan(Array.isArray(pageIndices) ? pageIndices : null)}>
            다시 검사
          </button>
          <button type="button" className={btnOutline} disabled={scanning || !hits.length} onClick={() => setVisibleChecked(true)}>
            모두 선택
          </button>
          <button type="button" className={btnOutline} disabled={scanning || !hits.length} onClick={() => setVisibleChecked(false)}>
            모두 해제
          </button>
          <span className="ml-2 text-sm text-slate-600">유형:</span>
          <select
            className={selectClass}
            value={typeFilter}
            disabled={scanning || !hits.length}
            onChange={(event) => setTypeFilter(event.target.value)}
          >
            <option value="">전체 유형</option>
            {labelCounts.map((item) => (
              <option key={item.label} value={item.label}>
                {`${item.display} (${item.count})`}
              </option>
            ))}
          </select>
          <button type="button" className={btnOutline} disabled={scanning || !typeFilter} onClick={selectTypeOnly}>
            이 유형만 선택
          </button>
          <label className="ml-auto flex items-center gap-1.5 text-sm text-slate-600">
            표시 방식:
            <select className={selectClass} value={styleId} onChange={(event) => setStyleId(event.target.value)}>
              {REDACT_STYLE_CHOICES.map((choice) => (
                <option key={choice.id} value={choice.id}>
                  {choice.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-slate-200 px-5 py-3">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="h-4 w-4 accent-app-accent"
              checked={onlyLocatable}
              onChange={(event) => {
                setOnlyLocatable(event.target.checked);
                recheckDefaults();
              }}
            />
            위치가 확인된 항목만 기본 선택
          </label>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">선택 {selectedCount}건</span>
            <button type="button" className={btnGhost} onClick={onClose}>
              취소
            </button>
            <button type="button" className={btnPrimary} disabled={!canApply} onClick={accept}>
              선택 항목 제거
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
