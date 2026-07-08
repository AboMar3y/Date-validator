"""
core/validator.py

Compares detected dates against the user-selected valid range and assigns
each one a ValidationStatus. This is intentionally a thin, pure module:
no I/O, no OCR — just business logic, which makes it trivial to unit test.
"""

from __future__ import annotations

from datetime import date

from config import CONFIDENCE_REVIEW_THRESHOLD
from utils.logger import get_logger
from utils.models import DetectedDate, FileResult, ScanSummary, ValidationStatus

logger = get_logger(__name__)


def validate_date(detected: DetectedDate, start: date, end: date) -> ValidationStatus:
    """Classify a single detected date.

    Priority order:
        1. Unparseable dates are reported as such (can't validate them).
        2. Low-confidence OCR results go to manual review regardless of
           whether the parsed value happens to fall in range — a wrong
           OCR read of a valid date is still not trustworthy.
        3. Otherwise, compare against [start, end] inclusive.
    """
    if detected.normalized_date is None:
        return ValidationStatus.UNPARSEABLE

    if detected.confidence < CONFIDENCE_REVIEW_THRESHOLD:
        return ValidationStatus.NEEDS_REVIEW

    if start <= detected.normalized_date <= end:
        return ValidationStatus.VALID

    return ValidationStatus.OUT_OF_RANGE


def validate_file_result(file_result: FileResult, start: date, end: date) -> None:
    """Mutates every DetectedDate inside a FileResult in place, setting
    its `.status` field based on the given range."""
    for page in file_result.pages:
        for detected in page.dates:
            detected.status = validate_date(detected, start, end)


def build_summary(file_results: list[FileResult], processing_seconds: float) -> ScanSummary:
    """Aggregate a list of FileResults into a top-level ScanSummary for
    display in the GUI and the Excel report's summary sheet."""
    total_files = len(file_results)
    total_pages = sum(len(f.pages) for f in file_results)
    all_dates = [d for f in file_results for p in f.pages for d in p.dates]
    total_dates = len(all_dates)
    total_out_of_range = sum(1 for d in all_dates if d.status == ValidationStatus.OUT_OF_RANGE)
    total_needs_review = sum(1 for d in all_dates if d.status == ValidationStatus.NEEDS_REVIEW)
    avg_confidence = (
        sum(d.confidence for d in all_dates) / total_dates if total_dates else 0.0
    )

    return ScanSummary(
        total_files=total_files,
        total_pages=total_pages,
        total_dates_detected=total_dates,
        total_out_of_range=total_out_of_range,
        total_needs_review=total_needs_review,
        processing_seconds=processing_seconds,
        average_confidence=round(avg_confidence, 1),
    )
