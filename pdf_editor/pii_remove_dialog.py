"""Dialog to review and redact detected personal information."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtCore import QThread, Qt, pyqtSignal
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
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from pdf_editor.pii_remove import (
    PiiHit,
    PiiScanResult,
    DEFAULT_REDACT_STYLE,
    REDACT_STYLE_CHOICES,
    RedactStyle,
    ScanCancelled,
    format_pii_count,
    format_pii_scope,
    hit_area_count,
    ko_pii_available,
    label_display,
    normalize_page_indices,
    scan_document_bytes,
)

PreviewCallback = Callable[[PiiHit, list[PiiHit]], None]


class _PiiScanWorker(QThread):
    progress = pyqtSignal(str)
    page_progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        pdf_bytes: bytes,
        parent=None,
        *,
        page_indices: Sequence[int] | None = None,
    ) -> None:
        super().__init__(parent)
        self._pdf_bytes = pdf_bytes
        self._page_indices = page_indices
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            result = scan_document_bytes(
                self._pdf_bytes,
                page_indices=self._page_indices,
                status_callback=self.progress.emit,
                progress_callback=self.page_progress.emit,
                cancel_callback=lambda: self._cancel,
            )
        except ScanCancelled:
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if self._cancel:
            return
        self.finished_ok.emit(result)


class PiiRemoveDialog(QDialog):
    """Scan the current PDF for Korean PII and choose items to redact."""

    def __init__(
        self,
        pdf_bytes: bytes,
        parent=None,
        *,
        preview_callback: PreviewCallback | None = None,
        bytes_provider: Callable[[], bytes] | None = None,
        page_indices: Sequence[int] | None = None,
    ) -> None:
        super().__init__(parent)
        self._pdf_bytes = pdf_bytes
        self._preview_callback = preview_callback
        self._bytes_provider = bytes_provider
        self._page_indices = normalize_page_indices(page_indices)
        self._hits: list[PiiHit] = []
        self._scan: PiiScanResult | None = None
        self._worker: _PiiScanWorker | None = None
        self._filter_label = ""
        self.setWindowTitle(self._window_title())
        self.setMinimumSize(720, 480)
        self._build_ui()
        self._start_scan()

    def _scope_label(self) -> str:
        return format_pii_scope(self._page_indices)

    def _window_title(self) -> str:
        scope = self._scope_label()
        if scope == "전체 페이지":
            return "개인정보 제거"
        return f"개인정보 제거 — {scope}"

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 12)

        scope = self._scope_label()
        if scope == "전체 페이지":
            title_text = "문서에서 개인정보를 찾아 원본 내용을 제거합니다."
        else:
            title_text = f"{scope}에서 개인정보를 찾아 원본 내용을 제거합니다."
        title = QLabel(title_text)
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        hint = QLabel(
            "검은 박스로 덮는 방식이 아니라 PDF 원본 텍스트를 삭제하는 "
            "레닥션입니다. 자동 탐지는 완전하지 않으니 저장 전 결과를 확인하세요.\n"
            "목록을 클릭하면 선택/해제되고, 미리보기의 빨간 상자가 "
            "실제로 지워지는 범위입니다.\n"
            "텍스트 레이어가 없는 스캔 PDF는 탐지되지 않을 수 있습니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(hint)

        self._status = QLabel("검사 준비 중…")
        self._status.setStyleSheet("color: #333;")
        root.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(True)
        root.addWidget(self._progress)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["선택", "페이지", "유형", "내용", "위치"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setColumnWidth(0, 48)
        self._table.setColumnWidth(1, 64)
        self._table.setColumnWidth(2, 110)
        self._table.setColumnWidth(3, 280)
        self._table.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self._table, 1)

        row = QHBoxLayout()
        self._btn_rescan = QPushButton("다시 검사")
        self._btn_rescan.clicked.connect(self._rescan)
        row.addWidget(self._btn_rescan)
        self._btn_all = QPushButton("모두 선택")
        self._btn_all.clicked.connect(lambda: self._set_all_checked(True))
        row.addWidget(self._btn_all)
        self._btn_none = QPushButton("모두 해제")
        self._btn_none.clicked.connect(lambda: self._set_all_checked(False))
        row.addWidget(self._btn_none)
        row.addWidget(QLabel("유형:"))
        self._type_combo = QComboBox()
        self._type_combo.addItem("전체 유형", "")
        self._type_combo.currentIndexChanged.connect(self._apply_type_filter)
        row.addWidget(self._type_combo)
        self._btn_type_only = QPushButton("이 유형만 선택")
        self._btn_type_only.clicked.connect(self._select_filtered_type_only)
        self._btn_type_only.setEnabled(False)
        row.addWidget(self._btn_type_only)
        row.addStretch(1)

        row.addWidget(QLabel("표시 방식:"))
        self._style_combo = QComboBox()
        for style, label in REDACT_STYLE_CHOICES:
            self._style_combo.addItem(label, style)
        default_index = self._style_combo.findData(DEFAULT_REDACT_STYLE)
        self._style_combo.setCurrentIndex(default_index if default_index >= 0 else 0)
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
        self._cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        root.addWidget(buttons)
        self._set_scan_controls_enabled(False)

    def _set_scan_controls_enabled(self, ready: bool) -> None:
        self._btn_rescan.setEnabled(ready)
        self._btn_all.setEnabled(ready)
        self._btn_none.setEnabled(ready)
        self._type_combo.setEnabled(ready)
        self._btn_type_only.setEnabled(ready and bool(self._filter_label))
        self._style_combo.setEnabled(ready)
        self._only_locatable.setEnabled(ready)
        self._table.setEnabled(ready)
        self._ok_button.setEnabled(ready and bool(self._hits))

    def _start_scan(self) -> None:
        if not ko_pii_available():
            self._progress.setRange(0, 1)
            self._progress.setValue(0)
            self._status.setText("ko-pii가 설치되어 있지 않습니다.")
            QMessageBox.critical(
                self,
                "개인정보 제거",
                "ko-pii 패키지가 필요합니다.\n\npip install ko-pii",
            )
            self._ok_button.setEnabled(False)
            return
        self._status.setText("개인정보 검사 중…")
        self._progress.setRange(0, 0)
        self._set_scan_controls_enabled(False)
        self._btn_rescan.setEnabled(False)
        self._cancel_button.setText("검사 취소")
        worker = _PiiScanWorker(
            self._pdf_bytes,
            self,
            page_indices=self._page_indices,
        )
        worker.progress.connect(self._status.setText)
        worker.page_progress.connect(self._on_scan_progress)
        worker.finished_ok.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _on_scan_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(current)

    def _on_scan_finished(self, scan: object) -> None:
        if not isinstance(scan, PiiScanResult):
            return
        self._scan = scan
        self._hits = list(scan.hits)
        self._populate_type_filter()
        self._populate_table()
        self._apply_type_filter()
        locatable = scan.locatable_count
        no_text = scan.pages_without_text
        self._status.setText(
            f"검출 {len(self._hits)}건 · 위치 확인 "
            f"{format_pii_count(locatable, scan.area_count)} · "
            f"텍스트 없는 페이지 {no_text} / {scan.pages_scanned}"
        )
        self._progress.setRange(0, max(1, scan.pages_scanned))
        self._progress.setValue(scan.pages_scanned)
        self._set_scan_controls_enabled(True)
        if not self._hits:
            self._ok_button.setEnabled(False)

    def _on_scan_failed(self, message: str) -> None:
        self._status.setText("검사 실패")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        QMessageBox.critical(self, "개인정보 제거", message)
        self._ok_button.setEnabled(False)
        self._btn_rescan.setEnabled(True)

    def _on_worker_finished(self) -> None:
        self._cancel_button.setText("취소")
        if self._scan is None and not self._status.text().startswith("검사 실패"):
            self._status.setText("검사를 취소했습니다.")
            self._progress.setRange(0, 1)
            self._progress.setValue(0)
            self._ok_button.setEnabled(False)
        self._btn_rescan.setEnabled(True)

    def _rescan(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._stop_worker()
        if self._bytes_provider is not None:
            try:
                latest = self._bytes_provider()
            except Exception as exc:
                QMessageBox.critical(self, "개인정보 제거", str(exc))
                return
            if latest:
                self._pdf_bytes = latest
        self._hits = []
        self._scan = None
        self._table.setRowCount(0)
        self._start_scan()

    def _stop_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        for signal in (
            worker.finished_ok,
            worker.failed,
            worker.progress,
            worker.page_progress,
            worker.finished,
        ):
            try:
                signal.disconnect()
            except TypeError:
                pass
        if worker.isRunning():
            worker.request_cancel()
            worker.wait(8000)
        self._worker = None

    def reject(self) -> None:
        self._stop_worker()
        super().reject()

    def closeEvent(self, event) -> None:
        self._stop_worker()
        super().closeEvent(event)

    def _populate_type_filter(self) -> None:
        self._type_combo.blockSignals(True)
        self._type_combo.clear()
        self._type_combo.addItem("전체 유형", "")
        counts: dict[str, int] = {}
        for hit in self._hits:
            counts[hit.label] = counts.get(hit.label, 0) + 1
        for label in sorted(counts, key=lambda key: label_display(key)):
            self._type_combo.addItem(
                f"{label_display(label)} ({counts[label]})",
                label,
            )
        self._type_combo.blockSignals(False)
        previous = self._filter_label
        index = self._type_combo.findData(previous)
        self._type_combo.setCurrentIndex(index if index >= 0 else 0)
        self._filter_label = str(self._type_combo.currentData() or "")

    def _populate_table(self) -> None:
        self._table.setRowCount(len(self._hits))
        for row, hit in enumerate(self._hits):
            check = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if hit.has_geometry:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            check.setFlags(flags)
            checked = bool(hit.has_geometry)
            if hit.has_geometry:
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

    def _visible_rows(self) -> list[int]:
        return [
            row
            for row in range(self._table.rowCount())
            if not self._table.isRowHidden(row)
        ]

    def _apply_type_filter(self) -> None:
        self._filter_label = str(self._type_combo.currentData() or "")
        for row, hit in enumerate(self._hits):
            hidden = bool(self._filter_label) and hit.label != self._filter_label
            self._table.setRowHidden(row, hidden)
        self._btn_type_only.setEnabled(bool(self._filter_label) and bool(self._hits))

    def _select_filtered_type_only(self) -> None:
        if not self._filter_label:
            return
        for row, hit in enumerate(self._hits):
            item = self._table.item(row, 0)
            if item is None or not hit.has_geometry:
                continue
            checked = hit.label == self._filter_label
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def _recheck_defaults(self) -> None:
        for row, hit in enumerate(self._hits):
            item = self._table.item(row, 0)
            if item is None or not hit.has_geometry:
                continue
            item.setCheckState(Qt.CheckState.Checked)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in self._visible_rows():
            hit = self._hits[row]
            item = self._table.item(row, 0)
            if item is None:
                continue
            if checked and not hit.has_geometry:
                continue
            if not hit.has_geometry:
                continue
            item.setCheckState(state)

    def _toggle_row(self, row: int) -> None:
        if not (0 <= row < len(self._hits)):
            return
        hit = self._hits[row]
        item = self._table.item(row, 0)
        if item is None or not hit.has_geometry:
            return
        if item.checkState() == Qt.CheckState.Checked:
            item.setCheckState(Qt.CheckState.Unchecked)
        else:
            item.setCheckState(Qt.CheckState.Checked)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column != 0:
            self._toggle_row(row)
        self._preview_row(row)

    def _preview_row(self, row: int) -> None:
        if self._preview_callback is None or not (0 <= row < len(self._hits)):
            return
        self._preview_callback(self._hits[row], self.selected_hits())

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
        return DEFAULT_REDACT_STYLE

    def _accept_if_ready(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        selected = self.selected_hits()
        if not selected:
            QMessageBox.information(
                self,
                "개인정보 제거",
                "제거할 항목을 선택하세요.\n위치가 확인된 항목만 적용됩니다.",
            )
            return
        summary = format_pii_count(len(selected), hit_area_count(selected))
        reply = QMessageBox.question(
            self,
            "개인정보 제거",
            f"선택한 {summary}의 원본 내용을 문서에서 삭제합니다.\n"
            "미리보기의 빨간 상자가 실제로 지워지는 범위입니다.\n"
            "이 작업은 저장 전에도 문서에 바로 반영되며, 실행 취소로 되돌릴 수 있습니다.\n\n"
            "계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.accept()
