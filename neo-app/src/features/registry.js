/**
 * ─── 기능 등록 지점 (frontend) ───────────────────────────────────────────────
 *
 * 새 기능 화면은 `src/features/<id>/` 에 만들고 아래 배열의 첫 항목으로 둡니다.
 * 이 앱은 사이드바 없이 첫 화면만 보여 줍니다.
 * 서버 쪽 API 는 `electron/modules/` 에 등록합니다.
 *
 * @typedef {{
 *   id: string,
 *   label: string,
 *   icon?: string,
 *   component: import('react').ComponentType,
 * }} FeatureDefinition
 */
import DocumentTabs from './editor/DocumentTabs.jsx';

/** @type {FeatureDefinition[]} */
export const FEATURES = [{ id: 'editor', label: 'PDF 편집', icon: '📄', component: DocumentTabs }];
