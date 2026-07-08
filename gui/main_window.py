"""
gui/main_window.py

The main application window: date range pickers, drag-and-drop area,
file browser, scan/cancel controls, progress bar, results table, and
export buttons. This module wires the GUI to the worker thread and the
export modules, but contains no OCR or parsing logic itself.
"""

from __future__ import annotations

import os
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import DEFAULT_OUTPUT_DIR
from export.excel_exporter import export_report
from export.pdf_annotator import annotate_all_files
from gui.drag_drop_widget import DragDropArea
from gui.worker import ScanWorker
from utils.logger import get_logger
from utils.models import FileResult, ScanSummary, ValidationStatus

logger = get_logger(__name__)

_STATUS_COLORS = {
    ValidationStatus.VALID: QColor("#d4edda"),
    ValidationStatus.OUT_OF_RANGE: QColor("#f8d7da"),
    ValidationStatus.NEEDS_REVIEW: QColor("#fff3cd"),
    ValidationStatus.UNPARSEABLE: QColor("#e2e3e5"),
}

_STYLESHEET = """
QMainWindow { background-color: #f5f6fa; }
QLabel#TitleLabel { font-size: 20px; font-weight: 600; color: #1f2d3d; }
QLabel#SubtitleLabel { font-size: 12px; color: #6b7785; }
QLabel#SectionLabel { font-size: 13px; font-weight: 600; color: #2c3e50; margin-top: 6px; }
QWidget#DragDropArea {
    background-color: #ffffff;
    border: 2px dashed #b8c2cc;
    border-radius: 10px;
}
QWidget#DragDropArea[dragActive="true"] {
    border: 2px dashed #3b82f6;
    background-color: #eef4ff;
}
QLabel#DragDropLabel { color: #6b7785; font-size: 13px; }
QPushButton {
    background-color: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    color: #2c3e50;
}
QPushButton:hover { background-color: #f0f3f7; }
QPushButton:disabled { color: #a9b3bd; background-color: #f5f6fa; }
QPushButton#PrimaryButton {
    background-color: #2563eb;
    color: white;
    border: none;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover { background-color: #1d4ed8; }
QPushButton#PrimaryButton:disabled { background-color: #a9c1f2; }
QPushButton#DangerButton {
    background-color: #dc2626;
    color: white;
    border: none;
}
QPushButton#DangerButton:hover { background-color: #b91c1c; }
QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e2e5e9;
    border-radius: 8px;
    gridline-color: #eef0f2;
}
QHeaderView::section {
    background-color: #eef1f5;
    padding: 6px;
    border: none;
    font-weight: 600;
    color: #2c3e50;
}
QProgressBar {
    border: 1px solid #d0d7de;
    border-radius: 6px;
    text-align: center;
    background-color: #ffffff;
    height: 22px;
}
QProgressBar::chunk { background-color: #2563eb; border-radius: 5px; }
QDateEdit {
    padding: 6px;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    background-color: #ffffff;
}
"""


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Date Range Validator")
        self.resize(1100, 750)
        self.setStyleSheet(_STYLESHEET)

        self._queued_files: list[str] = []
        self._results: list[FileResult] = []
        self._summary: ScanSummary | None = None
        self._worker: ScanWorker | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # --- Header ---
        title = QLabel("Date Range Validator")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("Scan documents, detect every date, and flag anything outside your valid range.")
        subtitle.setObjectName("SubtitleLabel")
        root.addWidget(title)
        root.addWidget(subtitle)

        # --- Date range row ---
        date_row = QHBoxLayout()
        start_label = QLabel("Start Date:")
        self.start_date_edit = QDateEdit(calendarPopup=True)
        self.start_date_edit.setDate(QDate.currentDate())
        self.start_date_edit.setDisplayFormat("MM/dd/yyyy")

        end_label = QLabel("End Date:")
        self.end_date_edit = QDateEdit(calendarPopup=True)
        self.end_date_edit.setDate(QDate.currentDate().addMonths(1))
        self.end_date_edit.setDisplayFormat("MM/dd/yyyy")

        date_row.addWidget(start_label)
        date_row.addWidget(self.start_date_edit)
        date_row.addSpacing(20)
        date_row.addWidget(end_label)
        date_row.addWidget(self.end_date_edit)
        date_row.addStretch()
        root.addLayout(date_row)

        # --- Drag and drop + browse ---
        files_label = QLabel("Documents")
        files_label.setObjectName("SectionLabel")
        root.addWidget(files_label)

        self.drop_area = DragDropArea()
        self.drop_area.files_dropped.connect(self._on_files_added)
        root.addWidget(self.drop_area)

        browse_row = QHBoxLayout()
        self.browse_button = QPushButton("Browse Files...")
        self.browse_button.clicked.connect(self._on_browse_clicked)
        self.clear_files_button = QPushButton("Clear Queue")
        self.clear_files_button.clicked.connect(self._on_clear_files)
        self.queued_count_label = QLabel("No files queued")
        browse_row.addWidget(self.browse_button)
        browse_row.addWidget(self.clear_files_button)
        browse_row.addStretch()
        browse_row.addWidget(self.queued_count_label)
        root.addLayout(browse_row)

        # --- Scan controls ---
        scan_row = QHBoxLayout()
        self.scan_button = QPushButton("Scan Documents")
        self.scan_button.setObjectName("PrimaryButton")
        self.scan_button.clicked.connect(self._on_scan_clicked)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("DangerButton")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.cancel_button.setEnabled(False)

        scan_row.addWidget(self.scan_button)
        scan_row.addWidget(self.cancel_button)
        scan_row.addStretch()
        root.addLayout(scan_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Idle")
        root.addWidget(self.progress_bar)

        # --- Results table ---
        results_label = QLabel("Results")
        results_label.setObjectName("SectionLabel")
        root.addWidget(results_label)

        self.results_table = QTableWidget(0, 7)
        self.results_table.setHorizontalHeaderLabels(
            ["File", "Page", "Detected Date", "Normalized", "Status", "Confidence", "Label"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        root.addWidget(self.results_table, stretch=1)

        self.summary_label = QLabel("")
        root.addWidget(self.summary_label)

        # --- Export controls ---
        export_row = QHBoxLayout()
        self.export_report_button = QPushButton("Export Report (Excel)")
        self.export_report_button.clicked.connect(self._on_export_report_clicked)
        self.export_report_button.setEnabled(False)

        self.export_pdf_button = QPushButton("Export Highlighted PDF")
        self.export_pdf_button.clicked.connect(self._on_export_pdf_clicked)
        self.export_pdf_button.setEnabled(False)

        export_row.addWidget(self.export_report_button)
        export_row.addWidget(self.export_pdf_button)
        export_row.addStretch()
        root.addLayout(export_row)

    # ------------------------------------------------------------------
    # File queue management
    # ------------------------------------------------------------------

    def _on_files_added(self, paths: list[str]) -> None:
        for path in paths:
            if path not in self._queued_files:
                self._queued_files.append(path)
        self._refresh_queue_label()

    def _on_browse_clicked(self) -> None:
        filter_str = "Documents (*.pdf *.jpg *.jpeg *.png *.tif *.tiff)"
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Documents", "", filter_str)
        if paths:
            self._on_files_added(paths)

    def _on_clear_files(self) -> None:
        self._queued_files.clear()
        self._refresh_queue_label()

    def _refresh_queue_label(self) -> None:
        n = len(self._queued_files)
        self.queued_count_label.setText(
            "No files queued" if n == 0 else f"{n} file{'s' if n != 1 else ''} queued"
        )

    # ------------------------------------------------------------------
    # Scan lifecycle
    # ------------------------------------------------------------------

    def _on_scan_clicked(self) -> None:
        if not self._queued_files:
            QMessageBox.warning(self, "No Files", "Please add at least one document to scan.")
            return

        start_qdate = self.start_date_edit.date()
        end_qdate = self.end_date_edit.date()
        start = date(start_qdate.year(), start_qdate.month(), start_qdate.day())
        end = date(end_qdate.year(), end_qdate.month(), end_qdate.day())

        if start > end:
            QMessageBox.warning(self, "Invalid Range", "Start Date must be on or before End Date.")
            return

        self.results_table.setRowCount(0)
        self.summary_label.setText("")
        self._results = []
        self._summary = None
        self.export_report_button.setEnabled(False)
        self.export_pdf_button.setEnabled(False)

        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting scan...")

        self._worker = ScanWorker(list(self._queued_files), start, end)
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.file_completed.connect(self._on_file_completed)
        self._worker.scan_finished.connect(self._on_scan_finished)
        self._worker.scan_error.connect(self._on_scan_error)
        self._worker.start()

    def _on_cancel_clicked(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.progress_bar.setFormat("Cancelling...")
            self.cancel_button.setEnabled(False)

    def _on_progress_updated(self, current: int, total: int, file_name: str) -> None:
        pct = int((current / total) * 100) if total else 0
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"Processing {current}/{total}: {file_name}")

    def _on_file_completed(self, file_result: FileResult) -> None:
        self._append_file_to_table(file_result)

    def _on_scan_finished(self, results: list[FileResult], summary: ScanSummary) -> None:
        self._join_worker()
        self._results = results
        self._summary = summary

        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setFormat("Scan complete")
        self.progress_bar.setValue(100)

        self.summary_label.setText(
            f"Files: {summary.total_files}  |  Pages: {summary.total_pages}  |  "
            f"Dates detected: {summary.total_dates_detected}  |  "
            f"Out of range: {summary.total_out_of_range}  |  "
            f"Needs review: {summary.total_needs_review}  |  "
            f"Avg. confidence: {summary.average_confidence}%  |  "
            f"Time: {summary.processing_seconds:.1f}s"
        )

        has_results = any(not f.error for f in results)
        self.export_report_button.setEnabled(True)  # report is useful even with errors listed
        self.export_pdf_button.setEnabled(has_results)

    def _on_scan_error(self, message: str) -> None:
        self._join_worker()
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setFormat("Error")
        QMessageBox.critical(self, "Scan Failed", f"An unexpected error occurred:\n{message}")

    # ------------------------------------------------------------------
    # Results table
    # ------------------------------------------------------------------

    def _append_file_to_table(self, file_result: FileResult) -> None:
        if file_result.error:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            self.results_table.setItem(row, 0, QTableWidgetItem(file_result.file_name))
            self.results_table.setItem(row, 1, QTableWidgetItem("—"))
            self.results_table.setItem(row, 2, QTableWidgetItem("—"))
            self.results_table.setItem(row, 3, QTableWidgetItem("—"))
            error_item = QTableWidgetItem(f"ERROR: {file_result.error}")
            error_item.setBackground(_STATUS_COLORS[ValidationStatus.UNPARSEABLE])
            self.results_table.setItem(row, 4, error_item)
            self.results_table.setItem(row, 5, QTableWidgetItem("—"))
            self.results_table.setItem(row, 6, QTableWidgetItem("—"))
            return

        for page in file_result.pages:
            if page.error:
                row = self.results_table.rowCount()
                self.results_table.insertRow(row)
                self.results_table.setItem(row, 0, QTableWidgetItem(file_result.file_name))
                self.results_table.setItem(row, 1, QTableWidgetItem(str(page.page_number)))
                error_item = QTableWidgetItem(f"ERROR: {page.error}")
                error_item.setBackground(_STATUS_COLORS[ValidationStatus.UNPARSEABLE])
                self.results_table.setItem(row, 4, error_item)
                continue

            for detected in page.dates:
                row = self.results_table.rowCount()
                self.results_table.insertRow(row)
                values = [
                    file_result.file_name,
                    str(page.page_number),
                    detected.raw_text,
                    detected.display_date,
                    detected.status.value,
                    f"{detected.confidence:.1f}%",
                    detected.nearby_label or "—",
                ]
                color = _STATUS_COLORS.get(detected.status)
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if color:
                        item.setBackground(color)
                    self.results_table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _on_export_report_clicked(self) -> None:
        if not self._results or self._summary is None:
            return
        default_path = os.path.join(DEFAULT_OUTPUT_DIR, "date_validation_report.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Save Excel Report", default_path, "Excel Files (*.xlsx)")
        if not path:
            return
        try:
            start_str = self.start_date_edit.date().toString("MM/dd/yyyy")
            end_str = self.end_date_edit.date().toString("MM/dd/yyyy")
            export_report(self._results, self._summary, start_str, end_str, path)
            QMessageBox.information(self, "Export Complete", f"Report saved to:\n{path}")
        except Exception as exc:
            logger.exception("Failed to export Excel report")
            QMessageBox.critical(self, "Export Failed", f"Could not save report:\n{exc}")

    def _on_export_pdf_clicked(self) -> None:
        if not self._results:
            return
        default_dir = os.path.join(DEFAULT_OUTPUT_DIR, "annotated_pdfs")
        directory = QFileDialog.getExistingDirectory(self, "Select Output Folder", default_dir)
        if not directory:
            return
        try:
            outputs = annotate_all_files(self._results, directory)
            QMessageBox.information(
                self, "Export Complete",
                f"{len(outputs)} annotated file(s) saved to:\n{directory}",
            )
        except Exception as exc:
            logger.exception("Failed to export annotated PDFs")
            QMessageBox.critical(self, "Export Failed", f"Could not save annotated PDFs:\n{exc}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        event.accept()

    def _join_worker(self) -> None:
        """Block briefly until the worker thread's OS thread has fully
        finished, so the QThread object can be safely dropped/reassigned
        without Qt warning about destroying a still-running thread. Since
        this is only called once the scan_finished/scan_error signal has
        already fired, the underlying work is done or finishing up, so
        this returns almost immediately in practice."""
        if self._worker is not None:
            self._worker.wait(5000)
