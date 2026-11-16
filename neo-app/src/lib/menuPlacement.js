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
