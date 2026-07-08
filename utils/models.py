"""
utils/models.py

Shared data structures used across the OCR, validation, export, and GUI
layers. Keeping these in one place avoids circular imports and gives every
module a single source of truth for what a "detected date" or "scan result"
looks like.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class ValidationStatus(str, Enum):
    """Result of comparing a detected date against the user's date range."""
    VALID = "Valid"
    OUT_OF_RANGE = "Out of Range"
    NEEDS_REVIEW = "Needs Manual Review"
    UNPARSEABLE = "Unparseable"


class SourceEngine(str, Enum):
    """Which OCR engine (or extraction method) produced a given detection.
    Useful for debugging accuracy issues later, and for the future
    template-learning feature."""
    TESSERACT = "Tesseract"
    EASYOCR = "EasyOCR"
    TEXT_LAYER = "PDF Text Layer"  # extracted directly from a born-digital PDF, no OCR needed


# Confidence threshold below which a detection is routed to manual review,
# regardless of whether it happens to fall inside the valid date range.
CONFIDENCE_REVIEW_THRESHOLD = 80.0


@dataclass
class BoundingBox:
    """Location of a detected text region.

    Two coordinate spaces are supported:
      - Pixel space (is_pdf_space=False): coordinates are pixels in a
        rasterized page image at `page_dpi`. This is what OCR produces.
      - PDF point space (is_pdf_space=True): coordinates are already in
        PDF points with a top-left origin, as returned directly by
        pdfplumber for born-digital text. No scaling is needed for these.
    """
    x: float
    y: float
    width: float
    height: float
    page_dpi: int = 300
    is_pdf_space: bool = False

    def to_pdf_rect(self, page_width_pt: float, page_height_pt: float,
                     image_width_px: int, image_height_px: int) -> tuple[float, float, float, float]:
        """Convert this bounding box into PDF point coordinates
        (x0, y0, x1, y1) for the given page size, so it can be drawn with
        PyMuPDF. PDF page origin is top-left when using PyMuPDF's rect API.
        """
        if self.is_pdf_space:
            return (self.x, self.y, self.x + self.width, self.y + self.height)

        scale_x = page_width_pt / image_width_px
        scale_y = page_height_pt / image_height_px
        x0 = self.x * scale_x
        y0 = self.y * scale_y
        x1 = (self.x + self.width) * scale_x
        y1 = (self.y + self.height) * scale_y
        return (x0, y0, x1, y1)


@dataclass
class DetectedDate:
    """A single date detection on a single page, before or after
    validation against the user's range."""
    raw_text: str                       # exact OCR text, e.g. "6 June 2026"
    normalized_date: Optional[date]      # parsed date, or None if unparseable
    confidence: float                    # 0-100, OCR engine confidence
    engine: SourceEngine
    bbox: BoundingBox
    nearby_label: Optional[str] = None   # e.g. "Inspection Date"
    format_inferred: bool = False        # True if MM/DD vs DD/MM was guessed
    ambiguous: bool = False              # True if the guess could be wrong
    status: ValidationStatus = ValidationStatus.UNPARSEABLE

    @property
    def display_date(self) -> str:
        return self.normalized_date.isoformat() if self.normalized_date else "—"


@dataclass
class PageResult:
    """All detections found on a single page of a single file."""
    page_number: int  # 1-indexed
    dates: list[DetectedDate] = field(default_factory=list)
    image_width_px: int = 0
    image_height_px: int = 0
    page_width_pt: float = 0.0
    page_height_pt: float = 0.0
    error: Optional[str] = None  # e.g. "OCR failed on this page"


@dataclass
class FileResult:
    """All results for a single scanned file (PDF or image)."""
    file_path: str
    file_name: str
    pages: list[PageResult] = field(default_factory=list)
    error: Optional[str] = None  # e.g. "Corrupted PDF", "Unsupported format"
    processing_seconds: float = 0.0

    @property
    def total_dates_detected(self) -> int:
        return sum(len(p.dates) for p in self.pages)

    @property
    def total_out_of_range(self) -> int:
        return sum(
            1 for p in self.pages for d in p.dates
            if d.status == ValidationStatus.OUT_OF_RANGE
        )

    @property
    def total_needs_review(self) -> int:
        return sum(
            1 for p in self.pages for d in p.dates
            if d.status == ValidationStatus.NEEDS_REVIEW
        )


@dataclass
class ScanSummary:
    """Top-level summary across an entire scan job, shown in the GUI and
    written to the Excel report's summary sheet."""
    total_files: int = 0
    total_pages: int = 0
    total_dates_detected: int = 0
    total_out_of_range: int = 0
    total_needs_review: int = 0
    processing_seconds: float = 0.0
    average_confidence: float = 0.0
