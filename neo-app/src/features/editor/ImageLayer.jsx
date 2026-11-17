import ImagePlaceOverlay from './ImagePlaceOverlay.jsx';
import { styleFromRect } from './imageBoxMath.js';

/**
 * 쪽 하나 위의 이미지 층: ① 이미 넣은 이미지를 눌러 고를 수 있는 투명 영역, ② 고른 이미지의 편집 오버레이,
 * ③ 옮길 때 보이는 정렬 안내선.
 */
export default function ImageLayer({ pageIndex, ptW, ptH, controller, showHits }) {
  const page = [0, 0, ptW, ptH];
  const selected = controller.items.filter((item) => item.pageIndex === pageIndex);
  const selectedIds = new Set(controller.items.map((item) => item.id).filter((id) => id != null));
  const hits = showHits ? (controller.stamps[pageIndex] || []).filter((stamp) => !selectedIds.has(stamp.id)) : [];
  const guides = controller.guides && controller.guides.pageIndex === pageIndex ? controller.guides.lines : [];

  return (
    <>
      {hits.map((stamp) => (
        <div
          key={stamp.id}
          data-img-hit="1"
          data-img-stamp={stamp.id}
          role="button"
          aria-label="이미지 선택"
          title="클릭하여 이미지 선택 (Shift+클릭: 여러 개)"
          className="absolute z-10 cursor-pointer hover:outline hover:outline-1 hover:outline-sky-400"
          style={styleFromRect(stamp.rect, page)}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.stopPropagation();
            void controller.selectStamp(stamp, event.shiftKey);
          }}
        />
      ))}
      {selected.map((item) => (
        <ImagePlaceOverlay
          key={item.key}
          item={item}
          eyedrop={controller.eyedrop}
          onBegin={controller.beginGesture}
          onMove={controller.moveGesture}
          onResize={controller.resizeTo}
          onEnd={controller.endGesture}
          onCommit={() => void controller.commit()}
          onPickColor={(key, fx, fy) => void controller.pickBackground(key, fx, fy)}
        />
      ))}
      {guides.map((line) => (
        <div
          key={`${line.axis}${line.pos}`}
          aria-hidden
          data-img-guide={line.axis}
          className="pointer-events-none absolute z-30 bg-fuchsia-500"
          style={
            line.axis === 'x'
              ? { left: `${(line.pos / ptW) * 100}%`, top: 0, width: 1, height: '100%' }
              : { top: `${(line.pos / ptH) * 100}%`, left: 0, height: 1, width: '100%' }
          }
        />
      ))}
    </>
  );
}
