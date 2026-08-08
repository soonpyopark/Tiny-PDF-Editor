"""Dialog to review and redact detected personal information."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from pdf_editor.pii_remove import (
    PiiHit,
    PiiScanResult,
    RedactStyle,
    ko_pii_available,
    label_display,
    scan_document_bytes,
)


class PiiRemoveDialog(QDialog):
    """Scan the current PDF for Korean PII and choose items to redact."""

    def __init__(self, pdf_bytes: bytes, parent=None) -> None:
        super().__init__(parent)
        self._pdf_bytes = pdf_bytes
        self._hits: list[PiiHit] = []
        self._scan: PiiScanResult | None = None
        self.setWindowTitle("개인정보 제거")
        self.setMinimumSize(720, 480)
        self._build_ui()
        self._run_scan()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 12)

        title = QLabel("문서에서 개인정보를 찾아 원본 내용을 제거합니다.")
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        hint = QLabel(
            "검은 박스로 덮는 방식이 아니라 PDF 원본 텍스트를 삭제하는 "
            "레닥션입니다. 자동 탐지는 완전하지 않으니 저장 전 결과를 확인하세요.\n"
            "텍스트 레이어가 없는 스캔 PDF는 탐지되지 않을 수 있습니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(hint)

        self._status = QLabel("검사 중…")
        self._status.setStyleSheet("color: #333;")
        root.addWidget(self._status)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["선택", "페이지", "유형", "내용", "위치"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setColumnWidth(0, 48)
        self._table.setColumnWidth(1, 64)
        self._table.setColumnWidth(2, 110)
        self._table.setColumnWidth(3, 280)
        root.addWidget(self._table, 1)

        row = QHBoxLayout()
        self._btn_all = QPushButton("모두 선택")
        self._btn_all.clicked.connect(lambda: self._set_all_checked(True))
        row.addWidget(self._btn_all)
        self._btn_none = QPushButton("모두 해제")
        self._btn_none.clicked.connect(lambda: self._set_all_checked(False))
        row.addWidget(self._btn_none)
        row.addStretch(1)

        row.addWidget(QLabel("표시 방식:"))
        self._style_combo = QComboBox()
        self._style_combo.addItem("검정 박스", RedactStyle.BLACK)
        self._style_combo.addItem("한글 라벨", RedactStyle.LABEL)
        row.addWidget(self._style_combo)
        root.addLayout(row)

        self._only_locatable = QCheckBox("위치가 확인된 항목만 기본 선택")
        self._only_locatable.setChecked(True)
        self._only_locatable.toggled.connect(self._recheck_defaults)
        root.addWidget(self._only_locatable)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("선택 항목 제거")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self._accept_if_ready)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        root.addWidget(buttons)

    def _run_scan(self) -> None:
        if not ko_pii_available():
            self._status.setText("ko-pii가 설치되어 있지 않습니다.")
            QMessageBox.critical(
                self,
                "개인정보 제거",
                "ko-pii 패키지가 필요합니다.\n\npip install ko-pii",
            )
            self._ok_button.setEnabled(False)
            return
        try:
            self._scan = scan_document_bytes(
                self._pdf_bytes,
                status_callback=self._status.setText,
            )
        except Exception as exc:
            self._status.setText("검사 실패")
            QMessageBox.critical(self, "개인정보 제거", str(exc))
            self._ok_button.setEnabled(False)
            return

        self._hits = list(self._scan.hits)
        self._populate_table()
        locatable = self._scan.locatable_count
        no_text = self._scan.pages_without_text
        self._status.setText(
            f"검출 {len(self._hits)}건 · 위치 확인 {locatable}건 · "
            f"텍스트 없는 페이지 {no_text} / {self._scan.pages_scanned}"
        )
        if not self._hits:
            self._ok_button.setEnabled(False)

    def _populate_table(self) -> None:
        self._table.setRowCount(len(self._hits))
        only_locatable = self._only_locatable.isChecked()
        for row, hit in enumerate(self._hits):
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            checked = hit.has_geometry if only_locatable else True
            if not hit.has_geometry:
                checked = False
            check.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            self._table.setItem(row, 0, check)

            page_item = QTableWidgetItem(str(hit.page_index + 1))
            page_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 1, page_item)

            self._table.setItem(row, 2, QTableWidgetItem(label_display(hit.label)))

            preview = hit.text
            if len(preview) > 80:
                preview = preview[:77] + "..."
            self._table.setItem(row, 3, QTableWidgetItem(preview))

            geo = "확인됨" if hit.has_geometry else "위치 없음(제외)"
            self._table.setItem(row, 4, QTableWidgetItem(geo))

    def _recheck_defaults(self) -> None:
        only_locatable = self._only_locatable.isChecked()
        for row, hit in enumerate(self._hits):
            item = self._table.item(row, 0)
            if item is None:
                continue
            if not hit.has_geometry:
                item.setCheckState(Qt.CheckState.Unchecked)
            elif only_locatable:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Checked)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row, hit in enumerate(self._hits):
            item = self._table.item(row, 0)
            if item is None:
                continue
            if checked and not hit.has_geometry:
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setCheckState(state)

    def selected_hits(self) -> list[PiiHit]:
        selected: list[PiiHit] = []
        for row, hit in enumerate(self._hits):
            item = self._table.item(row, 0)
            if item is None:
                continue
            if item.checkState() != Qt.CheckState.Checked:
                continue
            if not hit.has_geometry:
                continue
            selected.append(hit)
        return selected

    def selected_style(self) -> RedactStyle:
        data = self._style_combo.currentData()
        if isinstance(data, RedactStyle):
            return data
        return RedactStyle.BLACK

    def _accept_if_ready(self) -> None:
        selected = self.selected_hits()
        if not selected:
            QMessageBox.information(
                self,
                "개인정보 제거",
                "제거할 항목을 선택하세요.\n위치가 확인된 항목만 적용됩니다.",
            )
            return
        reply = QMessageBox.question(
            self,
            "개인정보 제거",
            f"선택한 {len(selected)}건의 원본 내용을 문서에서 삭제합니다.\n"
            "이 작업은 저장 전에도 문서에 바로 반영되며, 실행 취소로 되돌릴 수 있습니다.\n\n"
            "계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.accept()
