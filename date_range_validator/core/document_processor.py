"""
core/document_processor.py

Loads a file (PDF or image), rasterizes each page to an image, runs OCR,
extracts date candidates near field labels, and assembles the results into
the FileResult/PageResult data structures defined in utils/models.py.

This module deliberately contains no GUI code and no multiprocessing
orchestration — see gui/worker.py for how this gets called in parallel.
Keeping it standalone also makes it independently testable and reusable
(e.g. from a future CLI or network-folder batch mode).
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

import cv2
import fitz  # PyMuPDF
import numpy as np
import pdfplumber
from PIL import Image

from config import PDF_RENDER_DPI, SUPPORTED_EXTENSIONS
from core.date_parser import find_date_candidates
from core.ocr_engine import (
    OcrWord,
    find_label_words,
    find_nearby_label,
    group_words_into_lines,
    merge_ocr_results,
    preprocess_image,
    run_easyocr,
    run_tesseract,
    union_bbox,
    words_covering_span,
)
from utils.logger import get_logger
from utils.models import BoundingBox, DetectedDate, FileResult, PageResult, SourceEngine

logger = get_logger(__name__)

# Optional progress callback signature: (current_page, total_pages) -> None
ProgressCallback = Optional[Callable[[int, int], None]]


def _pil_to_cv2(pil_image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)


def _rasterize_page(fitz_page) -> np.ndarray:
    """Render a single PyMuPDF page to a BGR numpy image at PDF_RENDER_DPI.
    Only called for pages that don't have a usable text layer, since
    rasterizing + OCR is far more expensive than direct text extraction.
    """
    zoom = PDF_RENDER_DPI / 72.0  # PDF native resolution is 72 dpi
    matrix = fitz.Matrix(zoom, zoom)
    pix = fitz_page.get_pixmap(matrix=matrix)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    return img


def _load_pages_from_image(file_path: str) -> list[tuple[np.ndarray, float, float]]:
    """Load a single image file (JPG/PNG/TIFF) as one 'page'. TIFF files
    can be multi-page, so each frame is treated as a separate page."""
    pages = []
    pil_img = Image.open(file_path)
    frame_count = getattr(pil_img, "n_frames", 1)
    for i in range(frame_count):
        pil_img.seek(i)
        cv_img = _pil_to_cv2(pil_img)
        h, w = cv_img.shape[:2]
        # Treat 1 pixel = 1 point for images without an inherent PDF page
        # size; this only affects annotation scaling later, and images
        # get converted to a same-size PDF page during export anyway.
        pages.append((cv_img, float(w), float(h)))
    return pages


def extract_dates_from_words(all_words: list[OcrWord]) -> list[DetectedDate]:
    """Given a flat list of recognized words (from OCR, or from a PDF's
    embedded text layer), group them into lines, find date-like phrases
    spanning one or more words, and attach the nearest field label.

    This is shared by both the OCR pipeline and the born-digital
    text-layer fast path so the date-matching and label-proximity logic
    only needs to be correct in one place.
    """
    detections: list[DetectedDate] = []
    label_words = find_label_words(all_words)
    lines = group_words_into_lines(all_words)
    seen_spans: set[tuple[int, int, int]] = set()

    for line_idx, line in enumerate(lines):
        candidates = find_date_candidates(line.text)
        for matched_text, start, end, parsed in candidates:
            span_key = (line_idx, start, end)
            if span_key in seen_spans:
                continue
            seen_spans.add(span_key)

            covering_words = words_covering_span(line, start, end)
            if not covering_words:
                continue

            bbox = union_bbox(covering_words)
            confidence = min(w.confidence for w in covering_words)
            engines_used = set(w.engine for w in covering_words)
            engine = covering_words[0].engine if len(engines_used) > 1 else next(iter(engines_used))

            label = find_nearby_label(bbox, label_words)
            detections.append(DetectedDate(
                raw_text=matched_text,
                normalized_date=parsed.normalized,
                confidence=round(confidence, 1),
                engine=engine,
                bbox=bbox,
                nearby_label=label,
                format_inferred=parsed.format_inferred,
                ambiguous=parsed.ambiguous,
            ))

    return detections


def process_page(image_bgr: np.ndarray, page_width_pt: float, page_height_pt: float,
                  page_number: int) -> PageResult:
    """Run the full OCR + date-extraction pipeline on a single rasterized
    page image. Used for scanned/image pages (no usable PDF text layer)."""
    h, w = image_bgr.shape[:2]
    result = PageResult(
        page_number=page_number,
        image_width_px=w, image_height_px=h,
        page_width_pt=page_width_pt, page_height_pt=page_height_pt,
    )

    try:
        processed = preprocess_image(image_bgr)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Preprocessing failed on page %s, using raw image: %s", page_number, exc)
        processed = image_bgr

    try:
        tesseract_words = run_tesseract(processed, PDF_RENDER_DPI)
    except Exception as exc:
        logger.error("Tesseract failed on page %s: %s", page_number, exc)
        tesseract_words = []

    try:
        easyocr_words = run_easyocr(processed, PDF_RENDER_DPI)
    except Exception as exc:
        logger.error("EasyOCR failed on page %s: %s", page_number, exc)
        easyocr_words = []

    if not tesseract_words and not easyocr_words:
        result.error = "OCR failed to extract any text from this page."
        return result

    all_words = merge_ocr_results(tesseract_words, easyocr_words)
    result.dates = extract_dates_from_words(all_words)
    return result


# Minimum extracted characters for a PDF page to be treated as having a
# genuine, usable text layer. Scanned pages sometimes carry a handful of
# stray embedded characters (e.g. from a prior OCR pass baked in by the
# scanner) — a low threshold like this filters that noise out and routes
# the page to full OCR instead of trusting a near-empty text layer.
_MIN_TEXT_LAYER_CHARS = 20


def _extract_text_layer_words(pdfplumber_page) -> list[OcrWord]:
    """Pull words directly from a PDF page's embedded text layer via
    pdfplumber, with coordinates already in PDF point space. Confidence
    is set to 100 since this is exact digital text, not a recognition
    guess — there is no OCR uncertainty to model."""
    raw_words = pdfplumber_page.extract_words(keep_blank_chars=False)
    words: list[OcrWord] = []
    for w in raw_words:
        bbox = BoundingBox(
            x=w["x0"], y=w["top"],
            width=w["x1"] - w["x0"], height=w["bottom"] - w["top"],
            is_pdf_space=True,
        )
        words.append(OcrWord(text=w["text"], bbox=bbox, confidence=100.0, engine=SourceEngine.TEXT_LAYER))
    return words


def _page_has_embedded_image(fitz_page) -> bool:
    """True if the page contains any raster image object.

    This is the deciding factor for whether the text-layer fast path is
    safe to use. A page with zero embedded images was authored digitally
    (e.g. exported from Word/Excel) and cannot physically contain
    handwriting, so trusting its text layer is both safe and exact. A
    page with an embedded image might be a straight scan — including the
    common "searchable PDF" scanner output, which bakes in the scanner's
    own OCR text layer over the image. That baked-in layer is exactly the
    failure mode this check exists to catch: it can carry a full, healthy
    character count (so a naive length check would treat it as "digital
    text") while still having completely missed any handwritten fill-in
    on the page, since scanner-side OCR essentially never reads
    handwriting. So: any embedded image at all routes the page to full
    OCR instead, even if a text layer is also present.
    """
    try:
        return len(fitz_page.get_images(full=False)) > 0
    except Exception:  # pragma: no cover - defensive; treat as "might be a scan"
        return True


def _try_text_layer_page(pdfplumber_page, fitz_page, page_number: int,
                          page_width_pt: float, page_height_pt: float) -> Optional[PageResult]:
    """Attempt the fast path: extract dates directly from a PDF page's
    embedded text layer, skipping OCR entirely. Returns None (signaling
    the caller to fall back to rasterize-and-OCR) if the page contains
    any embedded image — see `_page_has_embedded_image` — or if the text
    layer is too sparse to be a genuine digital-text page.
    """
    if _page_has_embedded_image(fitz_page):
        return None

    words = _extract_text_layer_words(pdfplumber_page)
    total_chars = sum(len(w.text) for w in words)
    if len(words) < 3 or total_chars < _MIN_TEXT_LAYER_CHARS:
        return None

    result = PageResult(
        page_number=page_number,
        page_width_pt=page_width_pt, page_height_pt=page_height_pt,
    )
    result.dates = extract_dates_from_words(words)
    return result


def _process_pdf(file_path: str, progress_callback: ProgressCallback) -> list[PageResult]:
    """Process every page of a PDF using the hybrid strategy: try the
    born-digital text layer first (fast, exact), and only rasterize +
    run OCR on pages where that isn't available (genuine scanned pages).

    Mixed documents — e.g. a digitally-generated cover page followed by
    scanned attachments — are common in real business paperwork, so this
    check happens per-page rather than once for the whole file.
    """
    page_results: list[PageResult] = []

    fitz_doc = fitz.open(file_path)
    try:
        with pdfplumber.open(file_path) as plumber_doc:
            total_pages = len(fitz_doc)
            for i in range(total_pages):
                page_number = i + 1
                fitz_page = fitz_doc[i]
                page_width_pt, page_height_pt = fitz_page.rect.width, fitz_page.rect.height

                page_result = None
                try:
                    plumber_page = plumber_doc.pages[i]
                    page_result = _try_text_layer_page(
                        plumber_page, fitz_page, page_number, page_width_pt, page_height_pt
                    )
                except Exception as exc:
                    logger.warning("Text-layer extraction failed on page %s, falling back to OCR: %s",
                                   page_number, exc)
                    page_result = None

                if page_result is None:
                    # No usable text layer -> this is a scanned page; rasterize and OCR it.
                    try:
                        image = _rasterize_page(fitz_page)
                        page_result = process_page(image, page_width_pt, page_height_pt, page_number)
                    except Exception as exc:
                        logger.exception("Unhandled error processing page %s of %s", page_number, file_path)
                        page_result = PageResult(page_number=page_number, error=f"Processing error: {exc}")

                page_results.append(page_result)
                if progress_callback:
                    progress_callback(page_number, total_pages)
    finally:
        fitz_doc.close()

    return page_results


def process_file(file_path: str, progress_callback: ProgressCallback = None) -> FileResult:
    """Load and process every page of a single file, returning a
    fully-populated FileResult. Handles unreadable/corrupted files and
    unsupported formats gracefully rather than raising, since a single
    bad file should never abort a batch job.
    """
    file_name = os.path.basename(file_path)
    start_time = time.time()
    result = FileResult(file_path=file_path, file_name=file_name)

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        result.error = f"Unsupported file format: {ext}"
        return result

    if not os.path.isfile(file_path):
        result.error = "File not found or inaccessible."
        return result

    try:
        if ext == ".pdf":
            result.pages = _process_pdf(file_path, progress_callback)
        else:
            pages = _load_pages_from_image(file_path)
            total_pages = len(pages)
            for i, (image, pw, ph) in enumerate(pages, start=1):
                try:
                    page_result = process_page(image, pw, ph, i)
                except Exception as exc:
                    logger.exception("Unhandled error processing page %s of %s", i, file_name)
                    page_result = PageResult(page_number=i, error=f"Processing error: {exc}")
                result.pages.append(page_result)
                if progress_callback:
                    progress_callback(i, total_pages)
    except fitz.FileDataError:
        result.error = "Corrupted PDF: could not be opened."
        return result
    except Exception as exc:
        logger.exception("Failed to open file %s", file_path)
        result.error = f"Failed to open file: {exc}"
        return result

    if not result.pages:
        result.error = "No readable pages found in this file."
        return result

    result.processing_seconds = round(time.time() - start_time, 2)
    return result
