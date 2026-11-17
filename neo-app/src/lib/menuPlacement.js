import { useLayoutEffect, useRef } from 'react';

/**
 * 우클릭 메뉴를 화면 안에 맞춘다.
 * - 오른쪽/아래가 모자라면 커서 왼쪽/위로 뒤집는다.
 * - 그래도 모자라면 가장자리에 붙이고, 메뉴가 화면보다 크면 max-height 로 줄여 스크롤 가능하게 한다.
 * 측정은 useLayoutEffect 에서 하므로 화면에 한 프레임도 잘못된 위치로 보이지 않는다.
 */
export function placeMenu(element, x, y, margin = 4) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  element.style.maxHeight = `${vh - margin * 2}px`;
  element.style.overflowY = 'auto';

  const { width, height } = element.getBoundingClientRect();
  const visibleW = Math.min(width, vw - margin * 2);
  const visibleH = Math.min(height, vh - margin * 2);

  let left = x;
  if (left + visibleW > vw - margin) left = x - visibleW;
  left = Math.max(margin, Math.min(left, vw - visibleW - margin));

  let top = y;
  if (top + visibleH > vh - margin) top = y - visibleH;
  top = Math.max(margin, Math.min(top, vh - visibleH - margin));

  element.style.left = `${left}px`;
  element.style.top = `${top}px`;
}

/** 메뉴 요소 ref 를 돌려준다. open 이 true 가 되거나 좌표가 바뀔 때마다 화면 안으로 다시 배치한다. */
export function useMenuPlacement(open, x, y) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    if (open && ref.current) placeMenu(ref.current, x, y);
  }, [open, x, y]);
  return ref;
}

/**
 * 단추 아래(또는 옆)에 붙는 팝업을 화면 안에 맞춘다. 팝업은 position: fixed 로 두므로
 * 스크롤 영역·overflow 에 잘리지 않는다. 기준은 팝업의 부모 요소(보통 relative 래퍼)다.
 * - side 'bottom': 단추 아래, 왼쪽 맞춤. 오른쪽이 모자라면 단추 오른쪽 끝에 맞추고, 그래도 넘치면 화면 안으로 민다.
 *   아래가 모자라면 위로 뒤집고, 양쪽 다 모자라면 넓은 쪽에 맞춰 max-height + 스크롤.
 * - side 'right': 부모 항목 오른쪽(하위 메뉴). 모자라면 왼쪽으로 뒤집는다.
 */
export function placeAnchored(element, anchor, side = 'bottom', gap = 6, margin = 6) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  element.style.position = 'fixed';
  element.style.maxHeight = '';
  element.style.overflowY = '';
  element.style.left = '0px';
  element.style.top = '0px';

  const a = anchor.getBoundingClientRect();
  const width = Math.min(element.offsetWidth, vw - margin * 2);
  let height = element.offsetHeight;
  let left;
  let top;

  if (side === 'right') {
    left = a.right + gap;
    if (left + width > vw - margin) left = a.left - gap - width;
    left = Math.max(margin, Math.min(left, vw - width - margin));
    top = a.top;
    const room = vh - margin * 2;
    if (height > room) {
      element.style.maxHeight = `${room}px`;
      element.style.overflowY = 'auto';
      height = room;
    }
    top = Math.max(margin, Math.min(top, vh - height - margin));
  } else {
    left = a.left;
    if (left + width > vw - margin) left = a.right - width;
    left = Math.max(margin, Math.min(left, vw - width - margin));
    const below = vh - a.bottom - gap - margin;
    const above = a.top - gap - margin;
    const openBelow = height <= below || below >= above;
    const room = Math.max(80, openBelow ? below : above);
    if (height > room) {
      element.style.maxHeight = `${room}px`;
      element.style.overflowY = 'auto';
      height = room;
    }
    top = openBelow ? a.bottom + gap : a.top - gap - height;
    top = Math.max(margin, Math.min(top, vh - height - margin));
  }

  element.style.left = `${left}px`;
  element.style.top = `${top}px`;
}

/**
 * 팝업 요소 ref 를 받아, 열려 있는 동안 화면 안으로 배치한다.
 * 창 크기·스크롤·팝업 내용 크기가 바뀌면 다시 배치한다. 팝업 컴포넌트가 열릴 때만 마운트되면 open 은 true 로 둔다.
 */
export function useAnchoredPlacement(ref, { open = true, side = 'bottom', gap } = {}) {
  useLayoutEffect(() => {
    if (!open) return undefined;
    const element = ref.current;
    const anchor = element?.parentElement;
    if (!element || !anchor) return undefined;
    const gapPx = gap ?? (side === 'right' ? 2 : 6);
    const place = () => placeAnchored(element, anchor, side, gapPx);
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(place) : null;
    observer?.observe(element);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
      observer?.disconnect();
    };
  }, [ref, open, side, gap]);
}
