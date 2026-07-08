"""
config.py

Central place for constants and tunables. Nothing in here should require
touching other modules when changed — that's the point of keeping it
separate.
"""

from __future__ import annotations

import os
import sys


def _detect_bundled_tesseract() -> str:
    """If this app was packaged with PyInstaller and a Tesseract-OCR
    folder was bundled alongside the .exe (see build.spec + the
    GitHub Actions workflow in .github/workflows/), return the path to
    that bundled tesseract.exe so a packaged build needs zero separate
    Tesseract install on the machine that runs it. Returns "" if not
    found, in which case pytesseract falls back to searching PATH.
    """
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
        bundled = os.path.join(base_dir, "Tesseract-OCR", "tesseract.exe")
        if os.path.isfile(bundled):
            return bundled
    return ""


# --- OCR ---------------------------------------------------------------

# Rasterization DPI when converting PDF pages to images. Higher = better
# OCR accuracy (especially for handwriting) but slower and more memory.
PDF_RENDER_DPI = 300

# Path to the tesseract binary. Resolution order:
#   1. TESSERACT_CMD environment variable, if set (manual override)
#   2. A Tesseract-OCR folder bundled next to a packaged .exe
#   3. Otherwise left blank, and pytesseract searches the system PATH
TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "") or _detect_bundled_tesseract()

# EasyOCR language(s). English covers the date formats in this app's
# scope; add more codes here if the company's documents use other scripts.
EASYOCR_LANGUAGES = ["en"]

# Whether to use GPU acceleration for EasyOCR. Set to True only if a CUDA
# capable GPU + matching torch build is available; otherwise leave False
# for reliable free/offline CPU operation.
EASYOCR_USE_GPU = False

# --- Date parsing --------------------------------------------------------

# Regional default for ambiguous numeric dates like "03/04/2026", where it
# is genuinely unclear whether that means March 4th or April 3rd.
# "MDY" = month/day/year (US style), "DMY" = day/month/year.
AMBIGUOUS_DATE_DEFAULT = "MDY"

# Reasonable bounds for a "plausible" document date. Detections outside
# this window are still reported, but help filter obvious OCR noise
# (e.g. misread "2026" as "2028" would still land in-range, but a "0026"
# misread gets caught here).
MIN_PLAUSIBLE_YEAR = 1990
MAX_PLAUSIBLE_YEAR = 2100

# --- Validation ----------------------------------------------------------

CONFIDENCE_REVIEW_THRESHOLD = 80.0  # below this -> Needs Manual Review

# --- Labels used to locate date fields ------------------------------------

# Labels the field-locator looks for near a detected date. Matching is
# case-insensitive and tolerant of minor OCR noise (see core/date_parser.py
# for fuzzy matching). This list is intentionally easy to extend for new
# document templates without touching any detection logic.
DATE_FIELD_LABELS = [
    "date",
    "work date",
    "inspection date",
    "completion date",
    "issued",
    "issue date",
    "valid from",
    "valid to",
    "signed",
    "signature date",
    "expiration date",
    "expiry date",
    "due date",
]

# Max distance (in pixels, at PDF_RENDER_DPI) to consider a label "near" a
# date for attribution purposes. Purely cosmetic/informational — it does
# not affect whether a date is included, only what label is shown for it.
LABEL_PROXIMITY_PX = 250

# --- Performance -----------------------------------------------------------

# Number of worker processes for parallel document processing. None lets
# the OS decide (os.cpu_count()); cap it to avoid overwhelming low-end
# office machines.
MAX_WORKERS = min(4, os.cpu_count() or 2)

# --- Supported file types ---------------------------------------------------

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# --- Output ------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "DateRangeValidator_Output")

HIGHLIGHT_COLOR_INVALID = (1, 0, 0)      # red, PyMuPDF uses 0-1 RGB floats
HIGHLIGHT_COLOR_REVIEW = (1, 0.85, 0)    # yellow/amber
