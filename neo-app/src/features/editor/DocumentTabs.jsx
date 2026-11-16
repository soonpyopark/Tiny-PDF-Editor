import { useCallback, useEffect, useRef, useState } from 'react';
import { api as apiRaw } from '../../lib/apiClient.js';
import { useFullscreen } from '../../lib/fullscreen.js';
import EditorPage from './EditorPage.jsx';

/**
 * 문서 탭 묶음 (원본 Tiny 의 문서 탭).
 * - 탭 하나 = EditorPage 인스턴스 하나 = PDF 엔진 세션 하나.
 * - 활성 탭만 보이고, 숨은 탭은 상태를 유지한다.
 * - 첫 탭의 키는 '' 이고 엔진 세션은 창 식별자 그대로 쓴다 (기존 동작과 같다).
 * - 창 닫기 요청은 여기서 수정된 탭을 차례로 확인한 뒤 응답한다.
 */

const SELECTED_TAB =
  'bg-white text-slate-800 before:absolute before:inset-x-0 before:top-0 before:h-[2px] before:rounded-t-md before:bg-app-accent before:content-[\'\']';
const IDLE_TAB = 'bg-slate-100 text-slate-500 hover:bg-slate-200 hover:text-slate-800';

/** document window 로 넘어온 파일(?open=...)을 읽는다. 지우는 것은 마운트 뒤에 한다. */
function readOpenParam() {
  try {
    return new URL(window.location.href).searchParams.get('open') || '';
  } catch {
    return '';
  }
}

function clearOpenParam() {
  try {
    const url = new URL(window.location.href);
    if (!url.searchParams.has('open')) return;
    url.searchParams.delete('open');
    window.history.replaceState(null, '', url.toString());
  } catch {
    // URL 을 바꾸지 못해도 열기는 이미 끝났다.
  }
}

let tabSeq = 0;
function newTabKey() {
  tabSeq += 1;
  return `t${tabSeq}`;
}

function sameState(a, b) {
  return (
    Boolean(a) &&
    Boolean(b) &&
    a.name === b.name &&
    a.open === b.open &&
    a.modified === b.modified
  );
}

export default function DocumentTabs() {
  const [tabs, setTabs] = useState(() => [{ key: '', initialPath: readOpenParam() }]);
  const [activeKey, setActiveKey] = useState('');
  const [states, setStates] = useState(/** @type {Record<string, any>} */ ({}));

  // 콜백과 비동기 흐름에서 최신 값을 읽기 위한 참조
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;
  const activeRef = useRef(activeKey);
  activeRef.current = activeKey;
  const statesRef = useRef(states);
  statesRef.current = states;
  const controlsRef = useRef(/** @type {Map<string, { confirmClose: () => Promise<boolean>, closeDoc: () => void }>} */ (new Map()));

  useEffect(() => {
    clearOpenParam();
  }, []);

  const handleDocChange = useCallback((key, next) => {
    setStates((prev) => (sameState(prev[key], next) ? prev : { ...prev, [key]: next }));
  }, []);

  const registerControls = useCallback((key, controls) => {
    if (controls) controlsRef.current.set(key, controls);
    else controlsRef.current.delete(key);
  }, []);

  /** 새 탭으로 파일 열기 (설정이 '새 탭'일 때 EditorPage 가 부른다). */
  const openInNewTab = useCallback((filePath) => {
    const key = newTabKey();
    setTabs((prev) => [...prev, { key, initialPath: filePath }]);
    setActiveKey(key);
  }, []);

  const closeTab = useCallback(async (key) => {
    const controls = controlsRef.current.get(key);
    if (!controls) return;
    // 마지막 탭은 닫지 않고 빈 문서로 되돌린다 (원본: 마지막 탭을 닫으면 빈 문서 탭을 다시 만든다).
    if (tabsRef.current.length <= 1) {
      controls.closeDoc();
      return;
    }
    setActiveKey(key);
    const proceed = await controls.confirmClose();
    if (!proceed) return;

    const remaining = tabsRef.current.filter((tab) => tab.key !== key);
    if (!remaining.length) return;
    setTabs(remaining);
    setStates((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    if (activeRef.current === key) setActiveKey(remaining[remaining.length - 1].key);
    // 이 탭의 엔진 프로세스를 끈다. 첫 탭 세션도 같은 방식으로 정리된다.
    void apiRaw('pdf.closeTab', {}, { tab: key }).catch(() => undefined);
  }, []);

  // 창 닫기: 수정된 탭을 차례로 확인한다. 하나라도 취소하면 닫기를 막는다.
  useEffect(() => {
    const frame = window.frame;
    if (!frame?.onCloseRequest) return undefined;
    return frame.onCloseRequest(async () => {
      let proceed = true;
      try {
        for (const tab of tabsRef.current) {
          if (!statesRef.current[tab.key]?.modified) continue;
          const controls = controlsRef.current.get(tab.key);
          if (!controls) continue;
          setActiveKey(tab.key);
          proceed = await controls.confirmClose();
          if (!proceed) break;
        }
      } catch {
        // 확인 중 오류가 나도 응답은 반드시 보낸다. 안 보내면 메인 프로세스가 영원히 기다린다.
        proceed = false;
      }
      frame.respondClose(proceed);
    });
  }, []);

  // 전체화면에서는 탭 줄을 숨긴다 (원본: tabBar().hide()). 탭 아래 본문만 보인다.
  const fullscreen = useFullscreen();

  return (
    <div className="flex h-full min-h-0 flex-col">
      {!fullscreen && (
        <div
          role="tablist"
          className="flex h-10 shrink-0 items-end gap-1 overflow-x-auto border-b border-app-border bg-app-surface px-2"
        >
          {tabs.map((tab) => {
            const info = states[tab.key];
            const selected = tab.key === activeKey;
            const label = info?.name || '빈 문서(noname)';
            return (
              <div
                key={tab.key || 'main'}
                role="tab"
                aria-selected={selected}
                title={label}
                onClick={() => setActiveKey(tab.key)}
                className={`relative -mb-px flex h-9 min-w-[120px] max-w-[260px] shrink-0 cursor-pointer items-center gap-2 rounded-t-md border border-b-0 border-app-border pl-3 pr-1.5 text-[13px] ${
                  selected ? SELECTED_TAB : IDLE_TAB
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{label}</span>
                {info?.modified ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-app-accent" title="수정됨" /> : null}
                <button
                  type="button"
                  title="닫기"
                  aria-label="문서 닫기"
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
                  onClick={(event) => {
                    event.stopPropagation();
                    void closeTab(tab.key);
                  }}
                >
                  <svg viewBox="0 0 10 10" className="h-2.5 w-2.5" aria-hidden="true">
                    <path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
            );
          })}
        </div>
      )}

      {tabs.map((tab) => (
        <div
          key={tab.key || 'main'}
          className="flex min-h-0 flex-1 flex-col"
          style={{ display: tab.key === activeKey ? undefined : 'none' }}
        >
          <EditorPage
            tabKey={tab.key}
            active={tab.key === activeKey}
            initialPath={tab.initialPath}
            onDocChange={handleDocChange}
            onOpenInNewTab={openInNewTab}
            onRegisterControls={registerControls}
          />
        </div>
      ))}
    </div>
  );
}
