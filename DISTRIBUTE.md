# 배포판 사용 안내

버전·파일 이름 규칙은 `README.md`와 동일합니다.
(`Tiny PDF Editor v{버전}_YYMMDD_HHMMSS…`)

릴리스 다운로드: https://github.com/soonpyopark/Tiny-PDF-Editor/releases

## Windows — 설치판 (MSI)

1. `npm run build:dist:msi` 또는 `npm run build:release`로 `msi/` 폴더에 설치 파일을 만듭니다.
2. `msi/Tiny PDF Editor v{버전}_YYMMDD_HHMMSS.msi`를 더블 클릭해 설치합니다.
3. 관리자 권한 없이 **현재 사용자** 계정에 설치됩니다 (`%LocalAppData%`).
4. 설치 시 PDF 파일 연결(HKCU 레지스트리)과 시작 메뉴·바탕화면 바로가기가 등록됩니다.

WiX CLI 7 이상이 필요합니다.

```text
winget install WiXToolset.WiXCLI
wix eula accept wix7
```

## Windows — 포터블 zip

1. `npm run build:dist:portable` 또는 `npm run build:release`로 `msi/`에
   `Tiny PDF Editor v{버전}_YYMMDD_HHMMSS_portable.zip`을 만듭니다. (7-Zip 필요)
2. zip을 압축 해제한 뒤, 폴더 안의 `.exe`를 실행합니다.
3. Python 설치 없이 Windows에서 바로 실행됩니다.
4. exe와 `_internal` 폴더는 **같은 위치**에 두어야 합니다.

## Windows — 포터블 실행 (dist 폴더 배포)

1. `npm run build:dist:exe`로 `dist/`에 포터블 폴더를 만듭니다.
2. 배포 **폴더 전체**를 USB 또는 원하는 위치에 복사합니다.
3. 폴더 안의 `Tiny PDF Editor v{버전}_YYMMDD_HHMMSS.exe`를 더블 클릭합니다.

압축 해제가 필요 없는 폴더 배포도 가능합니다. 폴더 구조를 그대로 유지한 채 실행하세요.

## macOS — DMG / .app

1. `npm run build:dist:macos`로 `dist/`에 `.app`, `.dmg`, 맥용 OCR 팩(`OCR PACK_macOS_*.zip`)을 만듭니다. (Apple Silicon, 서명·공증 없음)
   DMG 파일명의 `YYMMDD_HHMMSS`가 앱의 `APP_BUILD_STAMP`와 같아 업데이트 확인에 사용됩니다.
2. DMG를 연 뒤 `Tiny PDF Editor.app`을 **응용 프로그램**으로 드래그합니다.
   OCR이 필요하면 같은 릴리스의 `OCR PACK_macOS_*.zip`을 OCR 폴더에 풀어 넣습니다.
3. 최초 실행 시 Gatekeeper 경고가 나오면 앱을 Control-클릭 → **열기**, 또는 **시스템 설정 → 개인정보 보호 및 보안**에서 허용합니다.

## OCR 팩 (선택)

메인 앱에는 OCR 엔진이 없습니다. 스캔·이미지 PDF 인식이 필요하면
같은 릴리스의 OS별 zip을 받아 OCR 폴더에 풉니다.

- Windows: `msi/OCR PACK_v{버전}_YYMMDD_HHMMSS.zip` (`npm run build:release` 또는 `npm run build:ocr`)
- macOS: `dist/OCR PACK_macOS_v{버전}_YYMMDD_HHMMSS.zip` (`npm run build:dist:macos`)

앱의 `OCR` → **OCR 팩 설치...**에서 폴더를 연 뒤 zip을 「여기에 풀기」하세요.
Windows 팩은 맥에서, 맥 팩은 Windows에서 동작하지 않습니다.

macOS에서는 다음 기능이 Windows 전용입니다.

- HWP/HWPX → PDF 변환 (한컴 한글 의존)
- PDF 파일 연결 메뉴

## USB 사용 (Windows)

- `dist` 안의 최신 빌드 폴더 또는 포터블 zip 압축 해제 폴더를 통째로 USB에 복사합니다.
- USB에서도 exe와 `_internal` 폴더가 **같은 위치**에 있어야 합니다.
- exe만 따로 복사하면 실행되지 않습니다.

## 시스템 요구 사항

- Windows 10 이상 (64비트)
- macOS 12 이상, Apple Silicon (arm64)
- 일반 기능은 오프라인 사용 가능
- 업데이트 확인만 인터넷 필요 (GitHub Releases)
- 한글 쪽 번호·텍스트 덮어쓰기: 시스템에 설치된 한글 글꼴 필요
  (Windows 맑은 고딕 등, macOS Apple SD Gothic Neo). 글꼴은 배포판에 포함하지 않습니다.
- HWP/HWPX (Windows): 한컴 한글 2020/2022/2024 설치 필요

## 주의 사항

- Windows Defender / macOS Gatekeeper에서 처음 실행 시 경고가 나올 수 있습니다. 직접 빌드한 배포본이라면 안내된 방법으로 실행을 허용하세요.
- 편집한 PDF는 **파일 → 저장** 또는 **다른 이름으로 저장**으로 저장하세요.
- **개인정보 제거**는 원본 텍스트를 삭제하는 레닥션입니다. 자동 탐지는 완전하지 않으니 저장 전 결과를 확인하세요.
- `*.msi`, `*_portable.zip`, `OCR PACK_*.zip` 등 대용량 산출물은 Git에 올리지 마세요 (100MB 제한).

## 라이선스

소스 코드는 MIT입니다. 배포판·OCR 팩 재배포 시 `LICENSE`의 서드파티 고지(PyMuPDF, PyQt6, RapidOCR, PP-OCR 모델 등)를 함께 제공하세요.

## 문의

프로그램 사용법은 `README.md`를 참고하세요.
개발자 홈페이지: https://note4all.tistory.com
