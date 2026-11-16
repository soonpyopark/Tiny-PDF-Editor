# Tiny PDF Editor - NEO 앱 (neo-app)

Tiny PDF Editor - neo 저장소 안의 Electron + React 화면입니다. 편집 엔진은 상위 폴더의 `pdf_editor/engine.py`를 씁니다. 실행은 상위 폴더에서 `npm run neo`, 재시작은 `npm run neo:restart`를 씁니다.

아래 내용은 앱 골격(로그인·설정·업데이트 등)에 대한 원래 설명입니다.

NAS4USB 류 앱을 만들 때 쓰는 Electron 기본 프레임. 로그인·회원·환경설정·백업·업데이트 확인이 이미 들어 있고, **기능만 추가**하면 된다.

## 명령

| 명령 | 설명 |
| --- | --- |
| `npm install` | 최초 1회 |
| `npm run dev` | 실행 (Electron 창 + 같은 포트의 웹 서버, HMR) |
| `npm run dev:restart` | 중지 후 재기동 |
| `npm run dev:stop` | 포트·Electron 프로세스를 모두 정리하고 종료 |
| `npm run build:release` | Windows MSI + portable zip → `release/` |
| `npm run build:release:mac` | macOS dmg + zip → `release/` (macOS 에서만 실행 가능) |
| `npm run version:bump` | 배포 버전 +1 (`APP_VERSION` `1.0.0.N`, `package.json` `1.0.0-N`). 옵션: `--set=1.1.0.0` `--sync` |
| `npm run publish:release` | 태그 `v1.0.0-N` + push + GitHub Release(msi·zip 업로드) + **이전 릴리스·태그 삭제**. 옵션: `--notes-file=` `--dry-run` `--keep-previous` |
| `npm run update:all` | npm(메이저 포함 `@latest`)·Electron·Python 엔진 패키지 최신화. 옵션: `--skip-git` `--skip-npm` `--skip-python` `--skip-majors` `--build` |
| `npm run build:update_all` | 최신화 + `build:release` (Windows). `update_all.bat` 으로도 실행 가능 (로그: `.cache/logs/update-all.log`) |
| `npm run build:update_all:mac` | 최신화 + `build:release:mac` (macOS) |

`npm run check:identity` 는 Default Framework 와 식별자(UpgradeCode·appId·포트 등)가 겹치지 않는지 검사합니다. 두 릴리스 빌드가 시작할 때 자동으로 실행됩니다.

산출물 이름: `TinyPDFEditor-NEO_<YYMMDD_HHMMSS>_<arch>.msi`, `TinyPDFEditor-NEO_portable_<stamp>_<arch>.zip`, `TinyPDFEditor-NEO_<stamp>_<arch>.dmg`.

기본 로그인: `admin` / `admin1234` (로그인 후 회원 관리에서 변경).
기본 포트 3021, 기본 접속 범위는 이 PC(127.0.0.1) 만. 환경설정 > 서버 관리에서 변경.

## 구조

- `main.js`, `preload.cjs` — Electron 진입점
- `electron/httpServer.js` — UI + `POST /api/<name>` RPC 를 한 포트로 서비스
- `electron/api/coreApi.js` — 기본 API (로그인, 회원, 설정, IP, 백업, 업데이트)
- `electron/services/*` — 설정·회원·인증·백업 등 서비스
- `shared/*` — 메인/화면 공용 코드 (`constants.js` 에 앱 이름·버전)
- `src/` — React 화면. `src/lib/apiClient.js` 가 API 클라이언트 (※ `src/api/` 폴더는 `/api/` 라우트와 충돌하므로 만들지 말 것)

## 기능 추가 방법

1. 화면: `src/features/<id>/` 를 만들고 `src/features/registry.js` 에 한 줄 등록 (2개 이상이면 사이드바 표시)
2. 서버 API: `electron/modules/<name>.js` 에서 `defineApi()` 로 등록하고 `electron/modules/index.js` 에 추가
3. 화면에서 호출: `api('이름', 본문)`
4. 환경설정 탭 추가: `src/components/settings/SettingsView.jsx` 의 탭 배열

## 데이터 위치

- 개발: `<프로젝트>/data`
- portable: exe 옆 `data` (zip 안에 `.portable` 표시 파일 포함)
- 설치형: 사용자 데이터 폴더 아래 `data`
- `APP_DATA_DIR` 환경변수로 재지정 가능

## 앱 이름·버전 바꾸기

`shared/constants.js`(`APP_NAME` / `APP_ID` / `APP_FILE_NAME`) 와 `package.json`(name/version/build.appId), `installer/Product.wxs` 의 UpgradeCode 를 새 앱에 맞게 바꾼다. MSI는 바탕화면·시작 메뉴 바로가기를 만들고, `APP_ID`를 바로가기·프로세스에 맞춰 작업표시줄 고정 아이콘이 재부팅 후에도 유지되게 한다.
