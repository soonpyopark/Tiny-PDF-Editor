import { useEffect, useRef, useState } from 'react';
import { useAppInfo } from '../../context/AppInfoContext.jsx';
import { useDialog } from '../../context/DialogContext.jsx';
import { useEditorCommands } from '../../features/editor/editorCommands.jsx';
import { api, getNative } from '../../lib/apiClient.js';
import { toggleFullscreen as toggleAppFullscreen, useFullscreen } from '../../lib/fullscreen.js';
import { runUpdateCheck } from '../../lib/updateCheckUi.js';
import AppLogo from '../common/AppLogo.jsx';

const isWindows = typeof navigator !== 'undefined' && /Windows/i.test(navigator.userAgent);

function item(id, label, extra = {}) {
  return { id, label, ...extra };
}

function sep(id) {
  return { id, type: 'separator' };
}

/**
 * In-window menu matching Tiny PDF Editor (파일 / 편집 / 기능 / 보기 / 도움말).
 */
export default function AppMenuBar() {
  const appInfo = useAppInfo();
  const dialog = useDialog();
  const { run, ready, docOpen } = useEditorCommands();
  const [openId, setOpenId] = useState('');
  const [subId, setSubId] = useState('');
  const fullscreen = useFullscreen();
  const [openTarget, setOpenTarget] = useState('tab');
  const [facing, setFacing] = useState(false);
  const [recent, setRecent] = useState(/** @type {string[]} */ ([]));
  const [updateChecking, setUpdateChecking] = useState(false);
  const [recentCtx, setRecentCtx] = useState(/** @type {null | { x: number, y: number, path: string }} */ (null));
  const rootRef = useRef(null);
  const recentCtxRef = useRef(null);

  useEffect(() => {
    void api('pdf.recent')
      .then((data) => setRecent(data.items ?? []))
      .catch(() => setRecent([]));
  }, [docOpen, openId]);

  useEffect(() => {
    void api('pdf.openTargetGet')
      .then((data) => setOpenTarget(data?.openInNewWindow ? 'window' : 'tab'))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!openId) return undefined;
    const onPointer = (event) => {
      if (!rootRef.current?.contains(event.target)) {
        setOpenId('');
        setSubId('');
      }
    };
    const onKey = (event) => {
      if (event.key === 'Escape') {
        setOpenId('');
        setSubId('');
      }
    };
    window.addEventListener('mousedown', onPointer);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', onPointer);
      window.removeEventListener('keydown', onKey);
    };
  }, [openId]);

  const closeMenus = () => {
    setOpenId('');
    setSubId('');
    setRecentCtx(null);
  };

  const openRecentContext = (event, filePath) => {
    event.preventDefault();
    setRecentCtx({ x: event.clientX, y: event.clientY, path: filePath });
  };

  // 목록에서 제거: 그 항목만 지우고 최근 목록을 다시 받는다. 다른 항목과 순서는 그대로 둔다.
  const removeRecent = (filePath) => {
    setRecentCtx(null);
    void api('pdf.recentRemove', { path: filePath })
      .then((data) => setRecent(data.items ?? []))
      .catch(() => undefined);
  };

  // 파일 위치 열기: 탐색기에서 해당 파일이 선택된 상태로 연다.
  const revealRecent = (filePath) => {
    setRecentCtx(null);
    void api('pdf.recentReveal', { path: filePath }).catch((error) => {
      void dialog.alert({
        title: '최근 파일',
        body: error instanceof Error ? error.message : '파일 위치를 열지 못했습니다.',
      });
    });
  };

  // 모두 지우기: 최근 파일 목록 전체를 비운다.
  const clearRecent = () => {
    void api('pdf.recentClear')
      .then((data) => setRecent(data.items ?? []))
      .catch(() => undefined);
  };

  // 최근 파일 우클릭 메뉴는 바깥을 누르거나 Esc 를 누르면 닫는다.
  useEffect(() => {
    if (!recentCtx) return undefined;
    const onPointer = (event) => {
      if (recentCtxRef.current?.contains(event.target)) return;
      setRecentCtx(null);
    };
    const onKey = (event) => {
      if (event.key === 'Escape') setRecentCtx(null);
    };
    window.addEventListener('mousedown', onPointer);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', onPointer);
      window.removeEventListener('keydown', onKey);
    };
  }, [recentCtx]);

  const go = (name, ...args) => {
    console.log('[AppMenuBar.go] Called with name:', name, 'args:', args);
    closeMenus();
    void run(name, ...args);
  };

  const checkUpdate = () => {
    if (updateChecking) return;
    closeMenus();
    setUpdateChecking(true);
    void runUpdateCheck(dialog).finally(() => setUpdateChecking(false));
  };

  const showAbout = () => {
    closeMenus();
    // Electron 창은 스플래시 형태의 정보 창을 쓰고, 브라우저(LAN 접속)는 기존 대화상자를 쓴다.
    const native = getNative();
    if (native?.showAboutSplash) {
      void native.showAboutSplash();
      return;
    }
    void dialog.alert({
      title: appInfo.name,
      icon: <AppLogo size={72} />,
      body: `버전: v${appInfo.version}\n빌드: ${appInfo.buildStampLabel}\n라이선스: MIT License`,
    });
  };

  const quit = () => {
    closeMenus();
    const native = getNative();
    if (native?.quit) {
      void native.quit();
      return;
    }
    window.close();
  };

  /** 원본 보기 > 새 창/새 탭으로 열기: 저장해 두고 다음 파일 열기부터 적용한다. */
  const chooseOpenTarget = (target) => {
    setOpenTarget(target);
    void api('pdf.openTargetSet', { openInNewWindow: target === 'window' }).catch(() => undefined);
  };

  const toggleFullscreen = () => {
    closeMenus();
    toggleAppFullscreen();
  };

  const needsDoc = !docOpen;
  const recentChildren = recent.length
    ? [
        ...recent.map((filePath, index) =>
          item(`recent-${index}`, filePath.split(/[/\\]/).pop() || filePath, {
            run: () => go('openRecent', filePath),
            // 원본: 최근 파일 행 우클릭 > 파일 위치 열기 / 목록에서 제거
            onContextMenu: (event) => openRecentContext(event, filePath),
          }),
        ),
        sep('recent-clear-sep'),
        // 원본: 최근 파일 하단 > 모두 지우기
        item('recent-clear', '모두 지우기', { run: () => clearRecent() }),
      ]
    : [item('recent-empty', '최근 파일 없음', { disabled: true })];

  const fileItems = [
    item('new', '새 문서', { shortcut: 'Ctrl+N', disabled: !ready, run: () => go('new') }),
    item('recent', '최근 파일 열기', { children: recentChildren }),
    item('open', '열기...', { shortcut: 'Ctrl+O', disabled: !ready, run: () => go('open') }),
    item('add', '추가...', { disabled: needsDoc, run: () => go('add') }),
    sep('file-1'),
    item('save', '저장', { shortcut: 'Ctrl+S', disabled: needsDoc, run: () => go('save') }),
    item('saveAs', '다른 이름으로 저장...', { shortcut: 'Ctrl+Shift+S', disabled: needsDoc, run: () => go('saveAs') }),
    item('images', '이미지로 저장...', { disabled: needsDoc, run: () => go('exportImages') }),
    sep('file-2'),
    item('print', '인쇄...', { shortcut: 'Ctrl+P', disabled: needsDoc, run: () => go('print') }),
    sep('file-3'),
    ...(isWindows ? [item('assoc', 'PDF 파일 연결...', { run: () => go('assoc') })] : []),
    item('printer', '가상 프린터...', { run: () => go('printer') }),
    sep('file-4'),
    item('quit', '종료', { shortcut: 'Ctrl+Q', run: quit }),
  ];

  const editItems = [
    item('undo', '되돌리기', { shortcut: 'Ctrl+Z', disabled: needsDoc, run: () => go('undo') }),
    item('redo', '재실행', { shortcut: 'Ctrl+Y', disabled: needsDoc, run: () => go('redo') }),
    sep('edit-1'),
    item('copy', '복사', { shortcut: 'Ctrl+C', disabled: needsDoc, run: () => go('copy') }),
    item('cut', '잘라내기', { shortcut: 'Ctrl+X', disabled: needsDoc, run: () => go('cut') }),
    item('paste', '붙여넣기', { shortcut: 'Ctrl+V', disabled: needsDoc, run: () => go('paste') }),
    sep('edit-2'),
    item('find', '텍스트 검색...', { shortcut: 'Ctrl+F', disabled: needsDoc, run: () => go('find') }),
    item('delete', '선택 페이지 삭제', { shortcut: 'Delete', disabled: needsDoc, run: () => go('delete') }),
    item('rotateCw', '모두 시계방향 회전', { disabled: needsDoc, run: () => go('rotateCw') }),
    item('rotateCcw', '모두 반시계방향 회전', { disabled: needsDoc, run: () => go('rotateCcw') }),
  ];

  // 기능: 원본 파일/OCR/보안 메뉴에 흩어져 있던 별도 기능을 한곳에 모았다. 기능끼리는 구분선으로 나눈다.
  const featureItems = [
    // 용량 줄이기·쪽 번호·서명은 기능 메뉴 맨 위에 둔다 (원래 편집 메뉴에 있던 항목).
    item('reduce', '용량 줄이기...', { disabled: needsDoc, run: () => go('reduce') }),
    item('pageNumber', '쪽 번호 매기기...', { disabled: needsDoc, run: () => go('pageNumber') }),
    // 쪽 위에 직접 그린다 (펜·연필·형광펜·지우개). 켜진 동안 체크 표시.
    item('draw', '그리기', { disabled: needsDoc, checked: Boolean(run('getDraw')), run: () => go('draw') }),
    item('signature', '서명 넣기', {
      disabled: needsDoc,
      children: [
        item('sigClip', '클립보드', { run: () => go('sigClip') }),
        item('sigFile', '파일 선택...', { run: () => go('sigFile') }),
      ],
    }),
    sep('fn-1'),
    item('ocr', 'OCR 변환하기...', { disabled: needsDoc, run: () => go('ocr') }),
    sep('fn-2'),
    item('pii', '개인정보 제거...', { disabled: needsDoc, run: () => go('pii') }),
    sep('fn-3'),
    item('setPw', '비밀번호 설정...', { disabled: needsDoc, run: () => go('setPw') }),
    item('clearPw', '비밀번호 제거', { disabled: needsDoc, run: () => go('clearPw') }),
    // PDF 변환(병합 / 개별 변환)은 문서를 새로 만드는 기능이라 맨 아래에 따로 둔다.
    sep('fn-4'),
    item('convert', 'PDF 변환...', { disabled: !ready, run: () => go('convert') }),
  ];

  const menus = [
    { id: 'file', label: '파일', mnemonic: 'f', items: fileItems },
    { id: 'edit', label: '편집', mnemonic: 'e', items: editItems },
    { id: 'function', label: '기능', mnemonic: 'u', items: featureItems },
    {
      id: 'view',
      label: '보기',
      mnemonic: 'v',
      items: [
        item('fitWidth', '너비 맞추기', { disabled: needsDoc, run: () => go('fitWidth') }),
        item('fitHeight', '높이 맞추기', { disabled: needsDoc, run: () => go('fitHeight') }),
        item('fitPage', '화면 맞추기', { disabled: needsDoc, run: () => go('fitPage') }),
        sep('view-1'),
        item('facing', '두 쪽씩 보기', {
          shortcut: 'Ctrl+2',
          checked: facing,
          run: () => {
            setFacing((value) => !value);
            go('facing');
          },
        }),
        sep('view-2'),
        item('fullscreen', '전체 화면', { shortcut: 'F11', checked: fullscreen, run: toggleFullscreen }),
        sep('view-3'),
        item('openWindow', '새 창으로 열기', {
          checked: openTarget === 'window',
          run: () => chooseOpenTarget('window'),
        }),
        item('openTab', '새 탭으로 열기', {
          checked: openTarget === 'tab',
          run: () => chooseOpenTarget('tab'),
        }),
      ],
    },
    {
      id: 'help',
      label: '도움말',
      mnemonic: 'h',
      items: [
        item('update', '업데이트 확인', { disabled: updateChecking, run: checkUpdate }),
        item('about', '정보(About)', { run: showAbout }),
      ],
    },
  ];

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      const key = event.key.toLowerCase();
      const ctrl = event.ctrlKey || event.metaKey;
      if (!ctrl && event.altKey && !event.shiftKey) {
        const menu = menus.find((entry) => entry.mnemonic === key);
        if (menu) {
          event.preventDefault();
          setOpenId(menu.id);
          setSubId('');
        }
        return;
      }
      if (ctrl && event.shiftKey && key === 's') {
        event.preventDefault();
        if (docOpen) void run('saveAs');
        return;
      }
      if (ctrl && key === 'n') {
        event.preventDefault();
        if (ready) void run('new');
        return;
      }
      if (ctrl && key === 'o') {
        event.preventDefault();
        if (ready) void run('open');
        return;
      }
      if (ctrl && key === 's') {
        event.preventDefault();
        if (docOpen) void run('save');
        return;
      }
      if (ctrl && key === 'p') {
        event.preventDefault();
        if (docOpen) void run('print');
        return;
      }
      if (ctrl && key === 'z') {
        event.preventDefault();
        if (docOpen) void run('undo');
        return;
      }
      if (ctrl && key === 'y') {
        event.preventDefault();
        if (docOpen) void run('redo');
        return;
      }
      if (ctrl && key === 'f') {
        event.preventDefault();
        if (docOpen) void run('find');
        return;
      }
      if (ctrl && key === '2') {
        event.preventDefault();
        setFacing((value) => !value);
        void run('facing');
        return;
      }
      if (ctrl && key === 'q') {
        event.preventDefault();
        quit();
        return;
      }
      if (event.key === 'Delete' && docOpen) {
        event.preventDefault();
        void run('delete');
        return;
      }
      if (event.key === 'F11') {
        event.preventDefault();
        toggleFullscreen();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  const activate = (entry) => {
    if (entry.disabled) return;
    if (entry.children) {
      setSubId((current) => (current === entry.id ? '' : entry.id));
      return;
    }
    entry.run?.();
    if (!entry.keepOpen) closeMenus();
  };

  return (
    <nav ref={rootRef} className="flex min-w-0 flex-wrap items-center" aria-label="메뉴">
      {menus.map((menu) => {
        const opened = openId === menu.id;
        return (
          <div key={menu.id} className="relative">
            <button
              type="button"
              className={`rounded-md px-2.5 py-1 text-sm ${
                opened ? 'bg-slate-100 font-medium text-slate-900' : 'text-slate-700 hover:bg-slate-100'
              }`}
              aria-expanded={opened}
              aria-haspopup="menu"
              onClick={() => {
                setSubId('');
                setOpenId((current) => (current === menu.id ? '' : menu.id));
              }}
              onMouseEnter={() => {
                if (openId) {
                  setOpenId(menu.id);
                  setSubId('');
                }
              }}
            >
              {menu.label}
            </button>
            {opened ? (
              <MenuPanel
                items={menu.items}
                subId={subId}
                onOpenSub={setSubId}
                onActivate={activate}
              />
            ) : null}
          </div>
        );
      })}
      {recentCtx ? (
        <div
          ref={recentCtxRef}
          role="menu"
          className="fixed z-[3000] min-w-[160px] rounded-md border border-slate-300 bg-white py-1 text-sm text-slate-800 shadow-lg"
          style={{
            left: Math.min(recentCtx.x, window.innerWidth - 180),
            top: Math.min(recentCtx.y, window.innerHeight - 48),
          }}
        >
          <button
            type="button"
            role="menuitem"
            className="flex w-full px-3 py-1.5 text-left hover:bg-slate-100"
            onClick={() => revealRecent(recentCtx.path)}
          >
            파일 위치 열기
          </button>
          <div className="my-1 h-px bg-slate-200" />
          <button
            type="button"
            role="menuitem"
            className="flex w-full px-3 py-1.5 text-left hover:bg-slate-100"
            onClick={() => removeRecent(recentCtx.path)}
          >
            목록에서 제거
          </button>
        </div>
      ) : null}
    </nav>
  );
}

function MenuPanel({ items, subId, onOpenSub, onActivate, nested = false }) {
  return (
    <div
      role="menu"
      className={`absolute z-40 min-w-56 rounded-md border border-app-border bg-white py-1 shadow-lg ${
        nested ? 'left-full top-0 ml-0.5' : 'left-0 top-full mt-1'
      }`}
    >
      {items.map((entry) => {
        if (entry.type === 'separator') {
          return <div key={entry.id} className="my-1 h-px bg-slate-200" role="separator" />;
        }
        const opened = subId === entry.id;
        return (
          <div
            key={entry.id}
            className="relative"
            onMouseEnter={() => onOpenSub(entry.children && !entry.disabled ? entry.id : '')}
          >
            <button
              type="button"
              role="menuitem"
              disabled={entry.disabled}
              className="flex w-full items-center gap-3 px-3 py-1.5 text-left text-sm text-slate-800 hover:bg-slate-100 disabled:cursor-default disabled:text-slate-300 disabled:hover:bg-transparent"
              onClick={() => onActivate(entry)}
              onContextMenu={entry.onContextMenu}
            >
              <span className="w-4 shrink-0 text-center text-xs text-slate-500">{entry.checked ? '✓' : ''}</span>
              <span className="min-w-0 flex-1 whitespace-nowrap">{entry.label}</span>
              {entry.shortcut ? <span className="shrink-0 text-xs text-slate-400">{entry.shortcut}</span> : null}
              {entry.children ? <span className="shrink-0 text-xs text-slate-400">▸</span> : null}
            </button>
            {entry.children && opened ? (
              <MenuPanel items={entry.children} subId="" onOpenSub={() => {}} onActivate={onActivate} nested />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
