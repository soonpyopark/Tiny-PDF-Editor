import { useEffect, useMemo, useState } from 'react';
import { useDialog } from '../../context/DialogContext.jsx';
import { api } from '../../lib/apiClient.js';
import ThumbnailPanel from './ThumbnailPanel.jsx';

/** Matches pdf_editor/left_side_nav.py LEFT_SIDE_NAV_WIDTH. */
export const LEFT_SIDE_NAV_WIDTH = 44;

function ThumbnailIcon() {
  return (
    <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
      <rect x="1.75" y="1.75" width="14.5" height="14.5" rx="2.2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="6.2" cy="6.1" r="1.15" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3.2 14.2 6.8 9.4 9.3 11.8 11.6 8.6 14.8 14.2" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function HighlightIcon() {
  return (
    <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
      <g transform="translate(9 8) rotate(45) translate(-9 -8)">
        <rect x="6.2" y="1.6" width="5.6" height="6.2" rx="1.6" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="M6.2 7.8h5.6v1.3L9 13.2 6.2 9.1Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      </g>
      <path d="M2.2 16.2h13.6" stroke="#ffd54a" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

function CollapseAllIcon() {
  return (
    <svg viewBox="0 0 18 18" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3 5 8" />
      <path d="M9 3l4 5" />
      <path d="M3 10h12" />
      <path d="M3 13h12" />
      <path d="M3 16h12" />
    </svg>
  );
}

function ExpandAllIcon() {
  return (
    <svg viewBox="0 0 18 18" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3h12" />
      <path d="M3 6h12" />
      <path d="M3 9h12" />
      <path d="M9 16 5 11" />
      <path d="M9 16l4-5" />
    </svg>
  );
}

function ExcelExportIcon() {
  return (
    <svg viewBox="0 0 18 18" width="16" height="16" aria-hidden="true">
      <rect x="2" y="2" width="14" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M6.5 3v12M11.5 3v12M3 6.5h12M3 11.5h12" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <rect x="3.2" y="3.2" width="3.1" height="3.1" fill="#217346" />
    </svg>
  );
}

const headerIconBtnClass =
  'inline-flex h-[26px] w-7 shrink-0 items-center justify-center rounded text-[#333] hover:bg-slate-100 disabled:opacity-50';

function cssColor(rgb) {
  const channel = (value) => Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 255);
  return `rgb(${channel(rgb?.[0])} ${channel(rgb?.[1])} ${channel(rgb?.[2])})`;
}

/**
 * Left rail from Tiny: LeftSideNavBar + content_stack (thumbnails / highlights).
 * Collapse hides content_stack only; nav stays. Toggle tab lives on the viewer (Tiny).
 */
export default function PageSide({
  docOpen,
  pageIndex,
  pageCount,
  thumbs,
  markups,
  clipboardCount,
  onSelectPage,
  onThumbAction,
  collapsed,
  onCollapsedChange,
  markupTabRequest = 0,
  pendingInsert = null,
}) {
  const dialog = useDialog();
  const [tab, setTab] = useState('thumbs');
  // 원본 _on_text_highlight_added: 첫 형광펜/밑줄이 생기면 목록 탭으로 바꾼다.
  useEffect(() => {
    if (markupTabRequest) setTab('highlights');
  }, [markupTabRequest]);
  const [expanded, setExpanded] = useState(/** @type {Record<number, boolean>} */ ({}));
  const [selectedKey, setSelectedKey] = useState('');
  const [exporting, setExporting] = useState(false);

  const groups = useMemo(() => {
    /** @type {{ pageIndex: number, entries: any[] }[]} */
    const pages = [];
    for (const entry of markups ?? []) {
      let group = pages.find((item) => item.pageIndex === entry.pageIndex);
      if (!group) {
        group = { pageIndex: entry.pageIndex, entries: [] };
        pages.push(group);
      }
      group.entries.push(entry);
    }
    return pages;
  }, [markups]);

  /** Same as DocumentTab._on_side_nav_tab_changed */
  const chooseTab = (next) => {
    if (!collapsed && tab === next) {
      onCollapsedChange(true);
      return;
    }
    setTab(next);
    if (collapsed) onCollapsedChange(false);
  };

  const exportExcel = async () => {
    if (!docOpen) {
      void dialog.alert({ title: '엑셀로 저장', body: '저장할 문서가 없습니다.' });
      return;
    }
    setExporting(true);
    try {
      const saved = await api('pdf.exportMarkups');
      if (saved.canceled) return;
      if (saved.empty) {
        void dialog.alert({ title: '엑셀로 저장', body: '저장할 형광펜·밑줄이 없습니다.' });
        return;
      }
      void dialog.alert({ title: '엑셀로 저장', body: '저장했습니다.' });
    } catch (err) {
      void dialog.alert({
        title: '엑셀로 저장',
        body: err instanceof Error ? err.message : '파일을 저장하지 못했습니다.',
      });
    } finally {
      setExporting(false);
    }
  };

  const tabs = [
    { id: 'thumbs', label: '썸네일', hint: '두번 클릭하면 메뉴가 사라집니다.', icon: <ThumbnailIcon /> },
    { id: 'highlights', label: '형광펜 & 밑줄', hint: '두번 클릭하면 메뉴가 사라집니다.', icon: <HighlightIcon /> },
  ];

  return (
    <div className="flex min-h-0 shrink-0">
      <nav
        className="flex shrink-0 flex-col border-r border-[#cccccc] bg-[#f5f5f5] pt-2"
        style={{ width: LEFT_SIDE_NAV_WIDTH }}
        aria-label="쪽 패널"
      >
        {tabs.map((item) => {
          const selected = tab === item.id && !collapsed;
          return (
            <button
              key={item.id}
              type="button"
              title={`${item.label}\n${item.hint}`}
              aria-label={item.label}
              aria-pressed={selected}
              className="mx-auto flex h-10 items-center justify-center text-[#333]"
              style={{ width: LEFT_SIDE_NAV_WIDTH }}
              onClick={() => chooseTab(item.id)}
            >
              <span className={`flex h-7 w-7 items-center justify-center rounded-md ${selected ? 'bg-[#e4e4e4]' : ''}`}>
                {item.icon}
              </span>
            </button>
          );
        })}
      </nav>

      {collapsed ? null : tab === 'thumbs' ? (
        <ThumbnailPanel
          docOpen={docOpen}
          thumbs={thumbs}
          pageIndex={pageIndex}
          pageCount={pageCount || thumbs.length || 0}
          clipboardCount={clipboardCount || 0}
          pending={pendingInsert}
          onSelectPage={onSelectPage}
          onAction={onThumbAction}
        />
      ) : (
        <aside className="flex w-64 shrink-0 flex-col border-r border-[#cccccc] bg-white">
          <div className="flex h-[34px] items-center gap-1 border-b border-[#cccccc] px-1">
            <span className="min-w-0 flex-1 truncate px-1 text-xs font-medium text-[#333]">형광펜 & 밑줄</span>
            <button
              type="button"
              className={headerIconBtnClass}
              title="모든 페이지 접기"
              aria-label="모든 페이지 접기"
              onClick={() => setExpanded(Object.fromEntries(groups.map((group) => [group.pageIndex, false])))}
            >
              <CollapseAllIcon />
            </button>
            <button
              type="button"
              className={headerIconBtnClass}
              title="모든 페이지 펴기"
              aria-label="모든 페이지 펴기"
              onClick={() => setExpanded(Object.fromEntries(groups.map((group) => [group.pageIndex, true])))}
            >
              <ExpandAllIcon />
            </button>
            <button
              type="button"
              className={`${headerIconBtnClass} bg-[#fde8e6] hover:bg-[#fbd0cb]`}
              title="형광펜·밑줄을 Excel로 저장"
              aria-label="엑셀로 저장"
              disabled={exporting}
              onClick={() => void exportExcel()}
            >
              <ExcelExportIcon />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {!docOpen ? (
              <p className="px-4 py-8 text-center text-[13px] leading-relaxed text-[#666]">문서에 페이지가 없습니다.</p>
            ) : markups == null ? (
              <p className="px-4 py-8 text-center text-[13px] text-[#666]">불러오는 중…</p>
            ) : groups.length === 0 ? (
              <p className="px-4 py-8 text-center text-[13px] leading-relaxed text-[#666]">형광펜이나 밑줄 친 내용이 없습니다.</p>
            ) : (
              groups.map((group) => {
                const open = expanded[group.pageIndex] !== false;
                return (
                  <section key={group.pageIndex}>
                    <button
                      type="button"
                      className="flex w-full items-center border-b border-[#e8e8e8] bg-[#efefef] px-2 py-1.5 text-left text-xs font-semibold text-[#333] hover:bg-[#e5e5e5]"
                      onClick={() => setExpanded((prev) => ({ ...prev, [group.pageIndex]: !open }))}
                    >
                      <span className="mr-1.5 text-[10px]">{open ? '▼' : '▶'}</span>
                      {group.pageIndex + 1}페이지
                    </button>
                    {open
                      ? group.entries.map((entry, index) => {
                          const key = `${group.pageIndex}-${index}`;
                          const color = cssColor(entry.rgb);
                          const selected = selectedKey === key;
                          return (
                            <button
                              key={key}
                              type="button"
                              onClick={() => {
                                setSelectedKey(key);
                                onSelectPage(entry.pageIndex);
                              }}
                              className={`flex w-full gap-2 px-2 py-2 text-left hover:bg-[#f7f7f7] ${selected ? 'ring-1 ring-inset ring-[#666]' : ''}`}
                            >
                              <span className="mt-0.5 h-4 w-1 shrink-0 rounded-sm" style={{ backgroundColor: color }} />
                              <span
                                className="min-w-0 flex-1 text-xs leading-relaxed text-[#333]"
                                style={entry.kind === 'underline' ? { textDecoration: 'underline', textDecorationColor: color } : undefined}
                              >
                                {entry.text}
                              </span>
                            </button>
                          );
                        })
                      : null}
                  </section>
                );
              })
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

/** Viewer-edge panel toggle — matches DocumentTab.panel_toggle_btn (parent=viewer, move(0,20)). */
export function PanelToggleTab({ collapsed, onToggle }) {
  const points = collapsed ? '5,3 11,8 5,13' : '9,3 3,8 9,13';
  return (
    <button
      type="button"
      title={collapsed ? '패널 펼치기' : '패널 접기'}
      aria-label={collapsed ? '패널 펼치기' : '패널 접기'}
      aria-expanded={!collapsed}
      onClick={onToggle}
      className="absolute left-0 top-5 z-30 flex h-12 w-3.5 items-center justify-center rounded-r-[7px] border border-l-0 border-[#cccccc] bg-[#e4e4e4] text-[13px] font-bold text-[#555] hover:bg-[#d3d3d3] hover:text-[#222]"
    >
      <svg viewBox="0 0 14 16" width="12" height="12" aria-hidden="true">
        <polygon points={points} fill="currentColor" />
      </svg>
    </button>
  );
}
