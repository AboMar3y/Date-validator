"""
gui/drag_drop_widget.py

A drop target area that accepts PDFs and images dragged from the file
explorer. Emits a Qt signal with the list of accepted file paths so the
main window can add them to its file queue.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from config import SUPPORTED_EXTENSIONS


class DragDropArea(QWidget):
    """Emits `files_dropped(list[str])` with the accepted, existing file
    paths whenever the user drops supported files onto this widget."""

    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("DragDropArea")
        self.setMinimumHeight(160)

        layout = QVBoxLayout(self)
        self._label = QLabel(
            "Drag & drop PDFs or images here\n(PDF, JPG, PNG, TIFF)"
        )
        self._label.setObjectName("DragDropLabel")
        self._label.setWordWrap(True)
        layout.addWidget(self._label, alignment=self._label.alignment())
        self._label.setAlignment(self._label.alignment() | self._center_alignment())

    @staticmethod
    def _center_alignment():
        from PySide6.QtCore import Qt
        return Qt.AlignmentFlag.AlignCenter

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt override)
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)

        paths: list[str] = []
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if not local_path or not os.path.isfile(local_path):
                continue
            ext = os.path.splitext(local_path)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                paths.append(local_path)

        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()
