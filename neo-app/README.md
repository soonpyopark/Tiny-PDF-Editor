# Tiny PDF Editor - NEO 앱 (neo-app)

Tiny PDF Editor - neo 저장소 안의 Electron + React 화면입니다. 편집 엔진은 상위 폴더의 `pdf_editor/engine.py`를 씁니다. 실행은 상위 폴더에서 `npm run neo`, 재시작은 `npm run neo:restart`를 씁니다.

**로컬 전용** PDF 에디터입니다. 로그인·회원·LAN 서버·설정 백업 UI는 없습니다. 창은 `127.0.0.1` HTTP로 UI를 띄웁니다.

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
| `npm run publish:release` | 태그 `v1.0.0-N` + push + GitHub Release(msi·zip 업로드) + 직전 릴리스 본문을 「이전 버전 이력」으로 이어 붙인 뒤 **이전 릴리스·태그 삭제**. 옵션: `--notes-file=` `--dry-run` `--keep-previous` |
| `npm run update:all` | npm(메이저 포함 `@latest`)·Electron·Python·OCR 모델(upstream 해시 바뀌면 핀 갱신) 최신화. 옵션: `--skip-git` `--skip-npm` `--skip-python` `--skip-ocr` `--skip-majors` `--build` |
| `npm run build:update_all` | 최신화 + `build:release` (Windows). `update_all.bat` 으로도 실행 가능 (로그: `.cache/logs/update-all.log`) |
| `npm run build:update_all:mac` | 최신화 + `build:release:mac` (macOS) |

`npm run check:identity` 는 Default Framework 와 식별자(UpgradeCode·appId·포트 등)가 겹치지 않는지 검사합니다. 두 릴리스 빌드가 시작할 때 자동으로 실행됩니다.

산출물 이름은 모두 가운데에 앱 버전, 그 뒤에 빌드 스탬프(`YYMMDD_HHMMSS`)가 들어갑니다. (이름은 `scripts/build-common.mjs` 의 `artifactBase()` 한 곳에서 만듭니다.)

| 산출물 | 이름 (예) |
| --- | --- |
| Windows MSI | `TinyPDFEditor-NEO-v1.0.0.3-261117_104722_x64.msi` |
| Windows 포터블 zip | `TinyPDFEditor-NEO-v1.0.0.3-portable-261117_104722_x64.zip` |
| macOS dmg | `TinyPDFEditor-NEO-v1.0.0.3-261117_104722_arm64.dmg` |
| macOS zip | `TinyPDFEditor-NEO-v1.0.0.3-mac-261117_104722_arm64.zip` |

`-portable-` / `-mac-` 는 업데이트 확인이 플랫폼별 zip 을 구분하는 표시이고, 스탬프는 같은 버전을 다시 빌드했을 때 새 빌드인지 비교하는 데 씁니다. 업데이트 확인(`shared/updateCheck.js`)은 예전 이름(`TinyPDFEditor-NEO_<stamp>_…`, `_portable_`, `_mac_`)도 읽습니다.

기본 포트 3021 (`127.0.0.1` 전용). 포트만 `data/settings.json` 의 `webServerPort` 또는 `APP_PORT` 로 바꿀 수 있습니다.

## 구조

- `main.js`, `preload.cjs` — Electron 진입점
- `electron/httpServer.js` — UI + `POST /api/<name>` RPC 를 한 포트로 서비스 (로컬 HTTP)
- `electron/api/coreApi.js` — 앱 정보·설정·업데이트 확인
- `electron/modules/pdf.js` — PDF 편집 API
- `shared/*` — 메인/화면 공용 코드 (`constants.js` 에 앱 이름·버전)
- `src/` — React 화면. `src/lib/apiClient.js` 가 API 클라이언트 (※ `src/api/` 폴더는 `/api/` 라우트와 충돌하므로 만들지 말 것)

## 기능 추가 방법

1. 화면: `src/features/<id>/` 를 만들고 `src/features/registry.js` 에 한 줄 등록 (2개 이상이면 사이드바 표시)
2. 서버 API: `electron/modules/<name>.js` 에서 `defineApi()` 로 등록하고 `electron/modules/index.js` 에 추가
3. 화면에서 호출: `api('이름', 본문)`
4. 환경설정 탭 추가: `src/components/settings/SettingsView.jsx` 의 탭 배열

## 데이터 위치

로컬 전용 앱입니다 (로그인·LAN 서버·설정 백업 UI 없음).

- 개발: `<프로젝트>/data`
- portable: exe 옆 `data` (zip 안에 `.portable` 표시 파일 포함)
- 설치형: 사용자 데이터 폴더 아래 `data`
- `APP_DATA_DIR` 환경변수로 재지정 가능

## 앱 이름·버전 바꾸기

`shared/constants.js`(`APP_NAME` / `APP_ID` / `APP_FILE_NAME`) 와 `package.json`(name/version/build.appId), `installer/Product.wxs` 의 UpgradeCode 를 새 앱에 맞게 바꾼다. MSI는 바탕화면·시작 메뉴 바로가기를 만들고, `APP_ID`를 바로가기·프로세스에 맞춰 작업표시줄 고정 아이콘이 재부팅 후에도 유지되게 한다.
