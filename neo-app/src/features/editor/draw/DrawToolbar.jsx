/** 그리기 모드 도구 막대. 뷰어 위쪽 가운데에 떠 있다. */
export default function DrawToolbar({ onDone }) {
  return (
    <div
      data-draw-toolbar="1"
      className="pointer-events-auto absolute left-1/2 top-2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-slate-300 bg-white/95 px-3 py-1.5 text-[12px] text-slate-700 shadow-md"
    >
      <span className="font-medium">그리기</span>
      <span className="text-slate-400">Esc 로 끝내기</span>
      <button
        type="button"
        className="rounded border border-slate-300 bg-white px-2 py-0.5 hover:bg-slate-50"
        onClick={onDone}
      >
        끝내기
      </button>
    </div>
  );
}
