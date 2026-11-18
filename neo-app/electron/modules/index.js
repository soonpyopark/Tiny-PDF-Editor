/**
 * ─── 기능 모듈 등록 지점 (backend) ───────────────────────────────────────────
 *
 * 새 기능을 추가할 때 이 폴더에 `electron/modules/<name>.js` 를 만들고
 * `register()` 에서 `defineApi()` 로 API 를 등록한 뒤, 아래 배열에 추가하세요.
 * 프론트엔드 쪽 등록 지점은 `src/features/registry.js` 입니다.
 */
import * as pdf from './pdf.js';

/** @type {{ register: () => void }[]} */
const MODULES = [pdf];

export function registerModules() {
  for (const mod of MODULES) mod.register();
}
