# Tiny PDF Editor

PDF 페이지를 병합·삭제·회전·보내기할 수 있는 데스크톱 편집기입니다.

## 설치

```bash
pip install -r requirements.txt
```

## 실행

```bash
python main.py
```

## Windows 배포판 빌드

```bash
npm install
npm run build:dist:exe
```

증분 업데이트(최신 `dist` 폴더에 변경 파일만 반영):

```bash
npm run build:dist:exe:update
```

`dist/` 폴더에 USB로 복사해 바로 실행할 수 있는 **포터블 폴더**가 생성됩니다.

```
dist/
  {프로젝트폴더명}_YYMMDD_HHMMSS/
    {프로젝트폴더명}_YYMMDD_HHMMSS.exe
    _internal/          (실행에 필요한 라이브러리)
    LICENSE
    README.md
    DISTRIBUTE.md
```

- 압축 없이 폴더 전체를 USB에 복사한 뒤 exe를 실행하면 됩니다.
- 빌드 폴더는 최근 **3개**만 유지됩니다.

## 주요 기능

### 썸네일 (왼쪽)
- **드래그 앤 드롭**: PDF 또는 이미지 파일을 썸네일 목록에 끌어다 놓으면 해당 위치에 페이지가 삽입됩니다.
- **다중 선택**: `Ctrl` + 클릭 또는 빈 공간에서 드래그하여 여러 페이지를 선택합니다.
- **삭제**: 선택 후 `Delete` 키, 툴바/썸네일 휴지통 버튼, 또는 우클릭 메뉴.
- **회전**: 시계/반시계 방향 회전 (툴바 버튼 또는 우클릭).
- **페이지 보내기**: 선택한 페이지만 새 PDF로 저장.
- **이미지로 보내기**: 선택한 페이지를 PNG/JPEG 파일로 저장.
- **썸네일 크기**: `+` / `-` 버튼으로 조절.

### 본문 보기 (오른쪽)
- 선택한 페이지 미리보기
- **너비/높이 맞추기**
- **페이지 이동**: 맨 앞 / 이전 / 다음 / 마지막
- **확대/축소**: 슬라이더, `+`/`-` 버튼, 퍼센트 직접 입력 (`Ctrl` + 마우스 휠도 가능)
- 페이지 크기(cm) 표시

### 파일
- **열기 / 저장 / 다른 이름으로 저장**
- **인쇄** (Windows 기본 PDF 인쇄)
- **탭**: 여러 문서를 탭으로 동시에 열기

## 지원 파일 형식 (삽입)

- PDF (`.pdf`)
- 이미지: PNG, JPEG, BMP, GIF, TIFF, WebP
# Tiny-PDF-Editor
