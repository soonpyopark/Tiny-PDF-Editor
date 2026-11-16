"""PyInstaller 진입점: 동결된 PDF 엔진 (resources/engine/tiny-pdf-engine.exe).

Electron 이 자식 프로세스로 띄우고 stdin/stdout 의 JSON 한 줄씩 주고받는다.
개발 실행에서는 이 파일을 쓰지 않고 `python -m pdf_editor.engine` 을 직접 띄운다.
"""

from __future__ import annotations

import sys

from pdf_editor.engine import main

if __name__ == "__main__":
    sys.exit(main())
