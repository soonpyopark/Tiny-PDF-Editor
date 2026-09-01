# Tiny PDF Editor v1.1.8

**포터블 PDF 편집기**입니다. Windows(exe·MSI·포터블 zip)와 macOS(`.app`·DMG) 배포판을 제공하며, 페이지 병합·편집·검색·용량 줄이기·쪽 번호 매기기·개인정보 제거 등 일상적인 PDF 작업을 한 프로그램에서 처리할 수 있습니다.

- 개발자 홈페이지: [https://note4all.tistory.com](https://note4all.tistory.com)
- GitHub: [https://github.com/soonpyopark/Tiny-PDF-Editor](https://github.com/soonpyopark/Tiny-PDF-Editor)
- 릴리스(설치·포터블 파일): [Releases](https://github.com/soonpyopark/Tiny-PDF-Editor/releases)

## 다운로드 및 실행

### Windows — 포터블 zip

1. 릴리스 또는 배포 페이지에서 `Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS_portable.zip`을 받습니다.
2. 압축을 푼 뒤, 폴더 안의 `Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS.exe`를 실행합니다.
3. `_internal` 폴더와 exe는 **같은 위치**에 있어야 합니다. exe만 따로 복사하면 실행되지 않습니다.

USB에 폴더 전체를 복사해 다른 PC에서도 사용할 수 있습니다.

### Windows — MSI 설치판

1. `Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS.msi`를 더블 클릭해 설치합니다.
2. 관리자 권한 없이 **현재 사용자** 계정에 설치됩니다 (`%LocalAppData%`).
3. 설치 시 PDF 파일 연결(HKCU)과 시작 메뉴·바탕화면 바로가기가 등록됩니다.
4. 설치 과정의 사용권 계약에는 [https://note4all.tistory.com](https://note4all.tistory.com)이 표시됩니다.
5. 동일 버전을 다시 설치하면 기존 설치를 제거한 뒤 새로 설치됩니다.

### macOS — DMG / .app

1. `Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS.dmg`를 열어 `Tiny PDF Editor.app`을 **응용 프로그램** 폴더로 복사합니다.
2. 앱을 실행합니다. (서명·공증되지 않은 빌드이므로 최초 실행 시 Gatekeeper 경고가 날 수 있습니다.)
3. 경고가 뜨면 앱을 **Control-클릭 → 열기**, 또는 **시스템 설정 → 개인정보 보호 및 보안**에서 허용하세요.

자세한 배포·USB 사용법은 `DISTRIBUTE.md`를 참고하세요.

### 시스템 요구 사항

- **Windows**: Windows 10 이상 (64비트)
- **macOS**: macOS 12 이상, Apple Silicon (arm64)
- 일반 편집은 **오프라인**으로 사용 가능합니다.
- **업데이트 확인**(`도움말` 메뉴)만 GitHub Releases 조회를 위해 인터넷이 필요합니다.
- 한글 텍스트 덮어쓰기·쪽 번호 매기기·개인정보 라벨 표시 시 시스템에 설치된 한글 글꼴이 사용됩니다. (Windows: 맑은 고딕 등, macOS: Apple SD Gothic Neo)
- HWP/HWPX 열기(Windows): PC에 **한컴 오피스 한글**(2020 / 2022 / 2024)이 설치되어 있어야 합니다.

> Windows Defender / macOS Gatekeeper에서 처음 실행 시 경고가 나올 수 있습니다. 직접 빌드하거나 신뢰하는 출처의 배포본이라면 안내된 방법으로 실행을 허용하세요.

---

## 주요 기능

### 파일 · 탭

- **새 문서** (`Ctrl+N`): 빈 탭을 엽니다.
- **최근 파일 열기**: 최근에 연 문서 목록에서 다시 엽니다.
- **열기...** (`Ctrl+O`): PDF·이미지·(Windows) HWP/HWPX를 엽니다. 여러 파일을 한 번에 선택하면 **한 탭에 순서대로 병합**됩니다. 파일이 많을 때는 **불러오기 진행 상태**가 표시됩니다.
- **추가...**: 현재 문서 **맨 뒤**에 PDF·이미지·(Windows) HWP/HWPX 페이지를 이어 붙입니다.
- **PDF 병합...**: 여러 파일을 골라 순서·미리보기를 확인한 뒤 새 PDF로 병합합니다. (HWP/HWPX 포함, Windows+한컴)
- **저장** (`Ctrl+S`) / **다른 이름으로 저장...** (`Ctrl+Shift+S`)
- **PDF를 이미지로 저장...**: 문서 페이지를 PNG/JPEG 등으로 보냅니다.
- **인쇄...** (`Ctrl+P`): 프린터 선택 대화상자에서 장치·범위를 고른 뒤 **직접 인쇄**합니다. 썸네일 우클릭으로 선택 페이지 또는 **전체 페이지 인쇄**도 할 수 있습니다.
- **PDF 파일 연결...** (Windows): 이 프로그램을 PDF 연결 프로그램 목록에 등록하거나 해제합니다.
- **탭**: 여러 PDF 문서를 동시에 열기. 탭을 닫을 때 저장 여부를 묻습니다.

### 보안 (`보안` 메뉴)

- **암호로 보호된 PDF 열기**: 열기 비밀번호 입력 대화상자가 표시됩니다.
- **비밀번호 설정...**: 저장 시 PDF 열기·소유자 비밀번호를 적용합니다.
- **비밀번호 제거**: 암호가 적용된 문서에서 비밀번호를 해제합니다. (저장 시 반영)
- **개인정보 제거...**: 주민등록번호·전화·계좌·성명·주소 등 한국어 개인정보를 **로컬**에서 탐지한 뒤, PDF **원본 텍스트를 삭제**하는 레닥션을 적용합니다.
  - 검출: [ko-pii](https://github.com/Marker-Inc-Korea/ko-pii) (MIT)
  - 표시: 검정 박스 또는 한글 라벨
  - 자동 탐지는 완전하지 않으며, 텍스트 레이어가 없는 스캔 PDF는 탐지가 어려울 수 있습니다. **저장 전 결과를 반드시 확인**하세요.

### 썸네일 (왼쪽)

- **드래그 앤 드롭**: PDF 또는 이미지를 끌어다 놓아 해당 위치에 페이지 삽입. 많은 파일·페이지를 불러올 때 **진행 상태**가 표시됩니다.
- **다중 선택**: `Ctrl` + 클릭, 또는 빈 공간 드래그
- **삭제**: `Delete` 키, 휴지통 버튼, 우클릭 메뉴
- **복사 / 잘라내기 / 붙여넣기**: 선택 페이지를 클립보드로 옮기거나 다른 위치에 붙여넣기
- **회전**: 시계/반시계 방향
- **페이지 보내기**: 선택 페이지만 새 PDF로 저장
- **이미지로 보내기**: 선택 페이지를 PNG/JPEG로 저장
- **선택 페이지 / 전체 페이지 인쇄**: 썸네일 우클릭. 한 장이면 `2페이지 인쇄`, 여러 장이면 `선택한 2개 페이지 인쇄`
- **선택 페이지 / 전체 페이지 개인정보 제거**: 썸네일 우클릭. 한 장이면 `2페이지 개인정보 제거`, 여러 장이면 `선택한 2개 페이지 개인정보 제거`. 보안 메뉴의 개인정보 제거는 전체 페이지와 같습니다.
- **썸네일 크기**: `+` / `-` 버튼으로 조절
- **패널 접기**: 썸네일·형광펜 탭 아이콘을 **같은 탭에서 다시 클릭**하거나, 패널 상단의 접기 탭 버튼으로 왼쪽 패널을 숨기고 미리보기 영역을 넓힐 수 있습니다.

### 형광펜 · 밑줄 (왼쪽 하단 탭)

- 본문에서 텍스트를 선택한 뒤 우클릭 메뉴로 **형광펜**·**밑줄**을 추가합니다.
- 왼쪽 **형광펜 & 밑줄** 패널에서 목록 확인, 항목 클릭으로 해당 위치로 이동, 삭제, **Excel로 보내기**가 가능합니다.
- 썸네일 탭과 같이 **같은 탭을 다시 클릭**하면 패널을 접을 수 있습니다.

### 본문 보기 (오른쪽)

- 선택 페이지 미리보기 (배경색 `#efefef`)
- **너비 / 높이 / 화면 맞추기**: 하단 `[너비]` `[높이]` `[화면]` 버튼 또는 **보기** 메뉴
  - 파일을 처음 열면 **화면 맞추기**가 기본으로 적용됩니다.
- **두 쪽씩 보기** (`Ctrl+2`): 좌·우 페이지를 나란히 표시합니다.
- **전체 화면** (`F11`): 메뉴·상태 표시줄·왼쪽 패널을 숨기고 미리보기와 하단 페이지 탐색 바만 표시합니다.
  - `Esc` 키 또는 화면 맨 위에 마우스를 올려 나타나는 닫기 버튼으로 해제합니다.
- **확대/축소**: 슬라이더(최대 **600%**), `Ctrl` + 마우스 휠
- **페이지 이동**: 맨 앞 / 이전 / 다음 / 마지막 버튼, 방향키·PageUp/PageDown
- **연속 스크롤** (`너비 맞추기` 모드): 스크롤·방향키로 다음 페이지로 넘어간 뒤 이전 페이지로 돌아가면, 해당 페이지 **맨 아래**부터 표시되어 위로 스크롤하며 읽을 수 있습니다.
- **페이지 크기 표시**: 하단에 `가로 x 세로 cm`와, 페이지에 임베드된 래스터 이미지가 있을 때 **생성 시 유효 DPI**를 함께 표시합니다.
- **텍스트 드래그 선택**: 미리보기에서 텍스트를 드래그해 선택하고 `Ctrl+C`로 복사
- **텍스트 덮어쓰기**: 텍스트가 있는 PDF에서 **한 줄을 더블클릭**하면 인라인 편집기가 열립니다. 수정 후 `Enter` 또는 다른 곳 클릭으로 반영, `Esc`로 취소합니다. (`Ctrl+Z` 되돌리기 지원)
- **스크롤바**: 미세한 반투명 스크롤바로 긴 페이지를 편하게 탐색합니다.

### 편집

- **되돌리기 / 재실행** (`Ctrl+Z`, `Ctrl+Y`): 페이지 삽입·삭제·회전·붙여넣기·텍스트 덮어쓰기·쪽 번호 매기기·개인정보 제거 등
- **텍스트 검색** (`Ctrl+F`, `F3` / `Shift+F3`): 본문 텍스트 검색, 하이라이트, `[ 현재 / 전체 ]` 결과 표시
- **선택 페이지 삭제** (`Delete`)
- **모든 페이지 시계방향 회전** / **모든 페이지 반시계방향 회전**
- **용량 줄이기** (`편집` 메뉴): PDF 파일 크기를 줄이는 도구 (아래 참고)
- **쪽 번호 매기기** (`편집` 메뉴): 위·아래 × 왼쪽/가운데/오른쪽에 쪽 번호를 넣거나, **쪽 번호 없음**으로 이 프로그램이 넣은 번호만 제거합니다.
  - 숫자 스타일(`1, 2, 3` / `i, ii, iii` / `I, II, III`), 줄표, 접두사·접미사
  - 시작 위치·시작 번호, 글자 크기, 쪽 번호 색상, 배경 색상(또는 투명)
  - 가로·세로 여백(0~30mm). 가운데 위치에서는 가로 여백을 쓰지 않습니다.
  - 한글 접두·접미는 시스템에 설치된 한글 글꼴이 필요합니다. 없으면 안내 후 적용하지 않습니다.
  - 원본 PDF에 이미 있는 쪽 번호는 지우지 않습니다. 흰 배경으로 가리거나, 투명 배경이면 겹쳐 보일 수 있습니다.

### 도움말

- **업데이트 확인**: GitHub Releases의 최신 **버전**과, 같으면 **현재 OS 배포 파일**의 빌드 시각(`YYMMDD_HHMMSS`)을 비교합니다.
  - Windows: `.msi` / `*_portable.zip`
  - macOS: `.dmg`
  - 새 버전이 있으면 다운로드 페이지를 엽니다.
- **About**: 앱 정보·버전을 표시합니다.

### 용량 줄이기

`편집` → **용량 줄이기...** 메뉴에서 사용합니다. 텍스트·레이아웃·검색은 유지하고 이미지 위주로 압축합니다. 진행 상태는 문서 하단 **터미널** 패널에 표시됩니다.

**이미지 설정 조정**

| 항목 | 기본값 | 설명 |
|------|--------|------|
| 이미지 압축 해상도 | 72 DPI | 재압축 기준 해상도 |
| 이미지 품질 | 100% | JPEG 품질 (낮출수록 용량 감소) |
| 이미지 사이즈 | 100% | 표시 크기 대비 다운샘플 비율 |

**콘텐츠 압축** (기본 모두 켜짐)

- 중복 리소스 제거
- 스트림 콘텐츠 압축
- 내장된 글꼴 압축

옵션을 조정한 뒤 **적용**을 누르면 현재 문서에 반영됩니다. 적용 후 **저장** 또는 **다른 이름으로 저장**으로 파일을 저장하세요.

> 스캔 PDF(JBIG2 등)처럼 일부 이미지는 처리에서 건너뛸 수 있습니다. 문제가 있는 이미지는 원본을 유지하고 나머지를 계속 처리합니다.

### 지원 파일 형식 (열기 · 추가 · 병합 · 드롭)

- PDF (`.pdf`) — 손상된 PDF는 가능한 범위에서 자동 복구를 시도합니다.
- 이미지: PNG, JPEG, BMP, GIF, TIFF, WebP
- HWP/HWPX (`.hwp`, `.hwpx`) — **Windows 전용** (한컴 한글 2020/2022/2024 필요). macOS에서는 지원하지 않습니다.

---

## 단축키 요약

| 동작 | 단축키 |
|------|--------|
| 새 문서 | `Ctrl+N` |
| 열기 | `Ctrl+O` |
| 저장 | `Ctrl+S` |
| 다른 이름으로 저장 | `Ctrl+Shift+S` |
| 인쇄 | `Ctrl+P` |
| 되돌리기 / 재실행 | `Ctrl+Z` / `Ctrl+Y` |
| 복사 / 잘라내기 / 붙여넣기 | `Ctrl+C` / `Ctrl+X` / `Ctrl+V` |
| 텍스트 검색 | `Ctrl+F` |
| 다음 / 이전 검색 결과 | `F3` / `Shift+F3` |
| 선택 페이지 삭제 | `Delete` |
| 두 쪽씩 보기 | `Ctrl+2` |
| 전체 화면 / 해제 | `F11` / `Esc` |
| 이전 / 다음 페이지 | `←` `↑` `PageUp` / `→` `↓` `PageDown` |
| 맨 앞 / 맨 뒤 페이지 | `Ctrl+Shift+←` / `Ctrl+Shift+→` |
| 확대/축소 | `Ctrl` + 마우스 휠 |

미리보기에서 텍스트를 선택한 상태에서는 `Ctrl+C`가 **선택 텍스트**를 복사합니다. 그 외에는 **선택 페이지**가 복사됩니다.

---

## 개발자용: 소스에서 실행

```bash
pip install -r requirements.txt
python main.py
```

의존성: PyMuPDF, PyQt6, openpyxl, ko-pii (`requirements.txt` 참고).

### Windows 배포판 빌드

Node.js가 설치되어 있어야 합니다.

**포터블 exe (폴더 배포)**

```bash
npm install
npm run build:dist:exe
```

증분 업데이트(최신 `dist` 폴더에 변경 파일만 반영):

```bash
npm run build:dist:exe:update
```

**MSI 설치판**

WiX CLI 7 이상이 필요합니다. (`winget install WiXToolset.WiXCLI`, `wix eula accept wix7`)

```bash
npm run build:dist:msi
```

**포터블 zip** (7-Zip 필요, MSI와 같은 `msi/` 폴더에 출력):

```bash
npm run build:dist:portable
```

**MSI + 포터블 zip (동일 빌드 시각, PyInstaller 1회)** — Neo Desktop Calendar의 `build:release`와 동일한 방식.
빌드 전에 릴리스용 Python/npm 패키지를 최신으로 맞춥니다 (`--skip-upgrade`로 생략 가능):

```bash
npm run build:release
```

산출물 예: `msi/Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS.msi`,
`msi/Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS_portable.zip`.
앱에 심어진 `APP_BUILD_STAMP`도 이 시각과 같아, 같은 태그로 재배포해도 업데이트 확인이 새 빌드를 구분합니다.

### macOS 배포판 빌드 (Apple Silicon)

Python 3.10+ 와 Node.js가 필요합니다. (권장: `.venv`에 Python 3.12)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
npm run build:dist:macos
```

DMG 파일명과 동일한 `APP_BUILD_STAMP`를 앱에 심으며, 업데이트 확인은 `.dmg` 자산만 비교합니다.

빌드 시 `assets/source_logo.png`가 있으면 `scripts/prepare-branding.py`가 아이콘·로고·`.icns`를 자동 생성합니다.

**포터블 빌드 결과** (`dist/`, Windows):

```
dist/
  Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS/
    Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS.exe
    _internal/          (실행에 필요한 라이브러리)
    LICENSE
    README.md
    DISTRIBUTE.md
```

**macOS 빌드 결과** (`dist/`):

```
dist/
  Tiny PDF Editor.app
  Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS/
    Tiny PDF Editor.app
    LICENSE
    README.md
    DISTRIBUTE.md
  Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS.dmg
```

**MSI / 포터블 zip 빌드 결과** (`msi/`):

```
msi/
  Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS.msi
  Tiny PDF Editor v1.1.8_YYMMDD_HHMMSS_portable.zip
```

포터블 빌드 폴더는 최근 **3개**만 유지됩니다.  
대용량 산출물(`*.msi`, `*_portable.zip`)은 Git에 올리지 않습니다 (`.gitignore`).

---

## 기술 스택

- Python 3, PyQt6 (Qt Print Support 포함)
- PyMuPDF (fitz) — 렌더링·편집·압축·레닥션·암호
- openpyxl — 형광펜·밑줄 Excel로 보내기
- ko-pii — 한국어 개인정보 검출 (`보안` → 개인정보 제거)
- Windows HWP 변환: 로컬 `hwp_to_pdf_helper` + 한컴 한글 COM (별도 한컴 설치 필요)

---

## 라이선스

본 프로젝트 소스 코드는 **MIT License**입니다. 자세한 내용은 `LICENSE` 파일을 참고하세요.

배포판(exe·MSI·포터블 zip·`.app`·DMG)에는 PyMuPDF, PyQt6 등 서드파티가 포함됩니다. 재배포할 때는 `LICENSE`의 서드파티 고지를 함께 제공해야 합니다.
