"""
gui/worker.py

Runs the document processing pipeline on a background QThread so the GUI
stays responsive, and fans work out across multiple processes (via
ProcessPoolExecutor) so multiple files are OCR'd in parallel — OCR is
CPU-bound, so processes (not threads) are used to get real parallelism
past Python's GIL.

Supports cancellation: the user can click Cancel and in-flight futures
are abandoned (already-started processes finish their current file, but
no new files are started).
"""

from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date

from PySide6.QtCore import QThread, Signal

from config import MAX_WORKERS
from core.document_processor import process_file
from core.validator import build_summary, validate_file_result
from utils.logger import get_logger
from utils.models import FileResult

logger = get_logger(__name__)


class ScanWorker(QThread):
    """Processes a batch of files in parallel and emits progress/results
    back to the main thread via Qt signals.

    Signals:
        progress_updated(int current, int total, str current_file)
        file_completed(FileResult)
        scan_finished(list[FileResult], ScanSummary)
        scan_error(str)
    """

    progress_updated = Signal(int, int, str)
    file_completed = Signal(object)       # FileResult
    scan_finished = Signal(list, object)  # list[FileResult], ScanSummary
    scan_error = Signal(str)

    def __init__(self, file_paths: list[str], start_date: date, end_date: date,
                 use_easyocr: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._file_paths = file_paths
        self._start_date = start_date
        self._end_date = end_date
        self._use_easyocr = use_easyocr
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation. Already-running file processes will
        finish their current file; no new ones will be started."""
        self._cancelled = True

    def run(self) -> None:  # noqa: C901 - orchestration naturally has some branching
        start_time = time.time()
        results: list[FileResult] = []
        total = len(self._file_paths)

        try:
            with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_path = {
                    executor.submit(process_file, path, None, self._use_easyocr): path
                    for path in self._file_paths
                }
                completed = 0
                for future in as_completed(future_to_path):
                    path = future_to_path[future]
                    if self._cancelled:
                        # Let already-submitted work finish naturally, but
                        # stop waiting/reporting on new completions.
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    try:
                        file_result: FileResult = future.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.exception("Worker process failed for %s", path)
                        file_result = FileResult(
                            file_path=path, file_name=path.split("/")[-1],
                            error=f"Processing failed: {exc}",
                        )

                    validate_file_result(file_result, self._start_date, self._end_date)
                    results.append(file_result)
                    completed += 1
                    self.progress_updated.emit(completed, total, file_result.file_name)
                    self.file_completed.emit(file_result)

        except Exception as exc:
            logger.exception("Fatal error during scan")
            self.scan_error.emit(str(exc))
            return

        elapsed = time.time() - start_time
        summary = build_summary(results, elapsed)
        self.scan_finished.emit(results, summary)