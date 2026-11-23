# 배포판 사용 안내 (Neo)

빌드 방법과 산출물 이름은 `neo-app/README.md`를 참고하세요.
산출물은 `neo-app/release/`에 만들어집니다.

- `TinyPDFEditor-NEO-v<버전>-<YYMMDD_HHMMSS>_<arch>.msi`
- `TinyPDFEditor-NEO-v<버전>-portable-<YYMMDD_HHMMSS>_<arch>.zip`

릴리스 다운로드: https://github.com/soonpyopark/Tiny-PDF-Editor/releases

## Windows — 설치판 (MSI)

1. `npm run build:release`로 `neo-app/release/`에 MSI를 만듭니다.
2. MSI를 더블 클릭해 설치합니다. 관리자 권한 없이 **현재 사용자** 계정에 설치됩니다 (`%LocalAppData%`).
3. 설치 시 시작 메뉴·바탕화면 바로가기가 등록되고, 설치 직후 인쇄 감시가 시작됩니다.
4. 앱을 처음 실행하면 가상 프린터 `Tiny PDF Editor`가 등록됩니다. (이후 `파일` → `가상 프린터...`에서 켜고 끌 수 있습니다.)

### 이전 Tiny PDF Editor (Legacy)가 있는 경우

같은 PC에 **Legacy MSI**(표시 이름 `Tiny PDF Editor`, 설치 폴더 `%LocalAppData%\Tiny PDF Editor`)가 있으면, Neo MSI 설치 과정에서 자동으로 제거한 뒤 Neo를 설치합니다. UpgradeCode는 서로 다르며, Neo가 Legacy를 “같은 제품 업그레이드”로 덮어쓰지 않고 별도로 찾아 제거합니다.

- 제거 대상: Legacy **MSI 설치본**만
- 제외: Legacy 포터블 zip·폴더 복사본(프로그램 추가/제거에 없음) — 필요하면 수동으로 지우세요
- Legacy 설정·최근 파일은 Neo로 옮기지 않습니다

WiX CLI 7 이상이 필요합니다.

```text
winget install WiXToolset.WiXCLI
wix eula accept wix7
```

### 이전 Neo 설치본이 있는 경우 (한 번만)

2026-11-17 이전에 만든 Neo MSI는 Default Framework와 **같은 UpgradeCode**를 쓰던 빌드입니다. 이후 빌드는 Neo 전용 UpgradeCode를 쓰므로, 새 MSI는 그 설치본을 업그레이드하지 않고 같은 폴더에 따로 설치하려 합니다. 먼저 이전 Neo를 **설정 → 앱**에서 제거한 뒤 새 MSI를 설치하세요. 설정·회원·백업은 `%APPDATA%`에 있어 제거해도 남습니다. 새 빌드부터는 이 단계가 필요 없습니다.

이 단계를 건너뛰면 이전 Neo 항목이 같은 설치 폴더·같은 파일을 붙잡고 있어서, 새 MSI가 일부 파일(특히 `Tiny PDF Editor - NEO.exe`)을 교체하지 못합니다. 그 상태에서 Electron 버전이 바뀌면 옛 exe 와 새 파일이 섞여 앱이 켜지자마자 꺼집니다 (`Version mismatch between V8 binary and snapshot`). 증상이 이렇다면 **설정 → 앱**에 `Tiny PDF Editor - NEO` 항목이 두 개 있는지 보고, 오래된 쪽을 제거한 뒤 최신 MSI로 수리(다시 설치)하세요.

## Windows — 포터블 zip

1. `npm run build:release`로 `neo-app/release/`에 `...-portable-....zip`을 만듭니다.
2. zip을 **폴더째** 압축 해제한 뒤 폴더 안의 `.exe`를 실행합니다.
3. Python 설치가 필요 없습니다. PDF 엔진(`resources/engine/tiny-pdf-engine.exe`)이 함께 들어 있습니다.
4. exe와 `resources` 폴더는 **같은 위치**에 두어야 합니다. exe만 따로 복사하면 실행되지 않습니다.
5. USB에서도 폴더째 복사해 실행할 수 있습니다.

## 인쇄 (가상 프린터)

- 다른 프로그램에서 `Tiny PDF Editor` 프린터로 인쇄하면 PDF가 Neo에서 열립니다.
- 앱이 **꺼져 있어도** 동작합니다. Chromium 없이 도는 가벼운 백그라운드 감시가 스풀 파일을 가져와 앱을 실행합니다.
- 앱을 종료한 직후에도 감시는 유지됩니다. Windows 로그인 시 자동으로 다시 시작됩니다. (HKCU Run: `TinyPDFEditorPrintWatch`)
- 앱이 켜져 있으면 새 탭(설정에 따라 새 창)으로 열립니다. 비어 있는 문서가 열려 있으면 그 자리에서 열립니다.
- 인쇄 결과는 `Downloads`에 `Tiny 인쇄 <YYMMDD_HHMMSS>.pdf`로 옮겨집니다.
- 가상 프린터를 끄면 감시와 로그인 자동 시작도 함께 해제됩니다.

## macOS — DMG / .app

- `npm run build:release:mac`(macOS에서만 실행 가능)으로 DMG를 만들 수 있습니다.
- **현재 macOS 빌드는 PDF 엔진을 포함하지 않고, 가상 프린터(PDF Services/CUPS) 흐름도 Neo로 이식되지 않았습니다.**
  macOS 배포 전에 별도 작업이 필요합니다.
- 최초 실행 시 Gatekeeper 경고가 나오면 앱을 Control-클릭 → **열기**, 또는 **시스템 설정 → 개인정보 보호 및 보안**에서 허용합니다.
- HWP/HWPX → PDF 변환, Windows 「PDF 파일 연결」 메뉴는 Windows 전용입니다.
- macOS: 앱 Info.plist 에 PDF 문서 타입이 있어 Finder 「다음으로 열기」에 표시됩니다 (기본 앱을 가로채지 않음). Applications 에 넣은 뒤 한 번 실행하면 Launch Services 에 등록됩니다.

## 시스템 요구 사항

- Windows 10 이상 (64비트)
- 일반 기능은 오프라인 사용 가능
- 업데이트 확인만 인터넷 필요 (GitHub Releases)
- 한글 쪽 번호·텍스트 덮어쓰기: 시스템에 설치된 한글 글꼴 필요
  (Windows 맑은 고딕 등). 글꼴은 배포판에 포함하지 않습니다.
- HWP/HWPX (Windows): 한컴 한글 2020/2022/2024 설치 필요

## 주의 사항

- Windows Defender(SmartScreen)에서 처음 실행 시 경고가 나올 수 있습니다. 직접 빌드한 배포본이라면 안내된 방법으로 실행을 허용하세요.
- 편집한 PDF는 **파일 → 저장** 또는 **다른 이름으로 저장**으로 저장하세요.
- **개인정보 제거**는 원본 텍스트를 삭제하는 레닥션입니다. 자동 탐지는 완전하지 않으니 저장 전 결과를 확인하세요.
- `*.msi`, `*_portable.zip` 등 대용량 산출물은 Git에 올리지 마세요 (100MB 제한).
- 예전 Tiny(PyQt) 버전의 `Tiny PDF Editor` 프린터와 로그인 감시 항목은 그대로 재사용됩니다. 이전 버전 exe가 지워졌다면 Neo를 한 번 실행하면 로그인 감시 항목이 복구됩니다.

## 라이선스

소스 코드는 MIT입니다. 배포판 재배포 시 `LICENSE`의 서드파티 고지(PyMuPDF, Electron 등)를 함께 제공하세요.

## 문의

프로그램 사용법은 `README.md`를 참고하세요.
개발자 홈페이지: https://note4all.tistory.com
