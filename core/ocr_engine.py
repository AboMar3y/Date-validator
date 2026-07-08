"""
core/ocr_engine.py

Wraps two free/offline OCR engines:
    - pytesseract (Tesseract): fast, good for printed text, word-level
      bounding boxes and confidence scores out of the box.
    - EasyOCR: slower but noticeably better on handwriting and stylized
      fonts; used as a second pass to catch what Tesseract misses.

Strategy: run both engines on each page. For each date candidate found by
either engine, keep the highest-confidence detection at that
approximate location (simple de-duplication by bounding-box overlap).

Also implements the label-based field locator: given all OCR word boxes
on a page, find text near known labels (e.g. "Inspection Date") so the
report can annotate dates with the field they most likely belong to,
without relying on any fixed template coordinates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract
from PIL import Image

from config import (
    DATE_FIELD_LABELS,
    EASYOCR_LANGUAGES,
    EASYOCR_USE_GPU,
    LABEL_PROXIMITY_PX,
    TESSERACT_CMD,
)
from utils.logger import get_logger
from utils.models import BoundingBox, SourceEngine

logger = get_logger(__name__)

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# EasyOCR's reader is expensive to initialize (loads model weights), so we
# lazily create one reader per process and reuse it across pages/files.
_easyocr_reader = None


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr  # imported lazily so app startup doesn't pay this cost
        logger.info("Initializing EasyOCR reader (first use, may take a moment)...")
        _easyocr_reader = easyocr.Reader(EASYOCR_LANGUAGES, gpu=EASYOCR_USE_GPU)
    return _easyocr_reader


@dataclass
class OcrWord:
    """A single recognized word/phrase with its location and confidence."""
    text: str
    bbox: BoundingBox
    confidence: float  # 0-100
    engine: SourceEngine


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """Clean up a scanned page image to improve OCR accuracy: grayscale,
    denoise, adaptive threshold, and deskew. Operates on a numpy array in
    BGR format (as loaded by OpenCV) and returns a processed BGR array
    suitable for feeding to both OCR engines.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Denoise while preserving edges (important for handwriting strokes).
    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    # Adaptive threshold handles uneven scan lighting better than a
    # global threshold would.
    thresh = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )

    # Deskew: estimate rotation angle from text line orientation and
    # correct it. Common with paper scans that go in slightly crooked.
    coords = np.column_stack(np.where(thresh < 255))
    if coords.shape[0] > 0:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) > 0.5:  # only correct meaningful skew, avoid noise
            (h, w) = thresh.shape
            center = (w // 2, h // 2)
            rot_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            thresh = cv2.warpAffine(
                thresh, rot_matrix, (w, h),
                flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
            )

    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)


def run_tesseract(image: np.ndarray, dpi: int) -> list[OcrWord]:
    """Run Tesseract OCR on an image and return word-level results with
    bounding boxes and confidence scores."""
    pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    data = pytesseract.image_to_data(
        pil_image, output_type=pytesseract.Output.DICT,
        config="--psm 11",  # sparse text mode: good for forms with scattered fields
    )

    words: list[OcrWord] = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        conf_raw = data["conf"][i]
        try:
            conf = float(conf_raw)
        except (ValueError, TypeError):
            conf = -1.0
        if not text or conf < 0:
            continue
        bbox = BoundingBox(
            x=data["left"][i], y=data["top"][i],
            width=data["width"][i], height=data["height"][i],
            page_dpi=dpi,
        )
        words.append(OcrWord(text=text, bbox=bbox, confidence=conf, engine=SourceEngine.TESSERACT))
    return words


def run_easyocr(image: np.ndarray, dpi: int) -> list[OcrWord]:
    """Run EasyOCR on an image and return results with bounding boxes and
    confidence scores. EasyOCR groups text into phrases rather than
    single words, which tends to work better for handwritten dates that
    span multiple tokens (e.g. "June 6, 2026")."""
    reader = _get_easyocr_reader()
    results = reader.readtext(image)  # list of (bbox_points, text, confidence)

    words: list[OcrWord] = []
    for bbox_points, text, confidence in results:
        text = text.strip()
        if not text:
            continue
        xs = [p[0] for p in bbox_points]
        ys = [p[1] for p in bbox_points]
        x0, y0 = int(min(xs)), int(min(ys))
        x1, y1 = int(max(xs)), int(max(ys))
        bbox = BoundingBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0, page_dpi=dpi)
        words.append(OcrWord(
            text=text, bbox=bbox, confidence=confidence * 100.0,
            engine=SourceEngine.EASYOCR,
        ))
    return words


def _boxes_overlap(a: BoundingBox, b: BoundingBox) -> bool:
    """Simple axis-aligned overlap test used to de-duplicate detections
    that both engines found at roughly the same location."""
    ax0, ay0, ax1, ay1 = a.x, a.y, a.x + a.width, a.y + a.height
    bx0, by0, bx1, by1 = b.x, b.y, b.x + b.width, b.y + b.height
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def merge_ocr_results(tesseract_words: list[OcrWord], easyocr_words: list[OcrWord]) -> list[OcrWord]:
    """Combine results from both engines. Where boxes overlap, keep the
    higher-confidence detection; otherwise keep both, since EasyOCR often
    catches handwriting Tesseract misses entirely and vice versa."""
    merged: list[OcrWord] = list(tesseract_words)
    for ez_word in easyocr_words:
        overlap_idx = None
        for i, t_word in enumerate(merged):
            if _boxes_overlap(ez_word.bbox, t_word.bbox):
                overlap_idx = i
                break
        if overlap_idx is None:
            merged.append(ez_word)
        elif ez_word.confidence > merged[overlap_idx].confidence:
            merged[overlap_idx] = ez_word
    return merged


def find_nearby_label(bbox: BoundingBox, label_words: list[OcrWord]) -> str | None:
    """Given a date's bounding box and a list of OCR words that matched
    known field labels, return the closest label within
    LABEL_PROXIMITY_PX, or None if nothing is close enough.

    This is what lets the app locate date fields "by structure" (label
    proximity) rather than fixed coordinates, per the requirement that
    templates vary across the company's documents.
    """
    if not label_words:
        return None

    date_cx = bbox.x + bbox.width / 2
    date_cy = bbox.y + bbox.height / 2

    best_label = None
    best_dist = float("inf")
    for label_word in label_words:
        lx = label_word.bbox.x + label_word.bbox.width / 2
        ly = label_word.bbox.y + label_word.bbox.height / 2
        dist = math.hypot(date_cx - lx, date_cy - ly)
        if dist < best_dist:
            best_dist = dist
            best_label = label_word.text

    if best_dist <= LABEL_PROXIMITY_PX:
        return best_label
    return None


@dataclass
class OcrLine:
    """A reconstructed line of text built by grouping nearby OCR words,
    used so multi-word date phrases like 'June 6, 2026' can be matched
    even though each word arrives as a separate detection box."""
    text: str
    words: list[OcrWord]
    word_spans: list[tuple[int, int]]  # (start_char, end_char) of each word within `text`


def group_words_into_lines(words: list[OcrWord], y_tolerance_ratio: float = 0.6) -> list[OcrLine]:
    """Group OCR words into lines based on vertical center proximity, then
    sort each line's words left-to-right. This is engine-agnostic (unlike
    relying on Tesseract's block/line/par indices), which matters since
    Tesseract and EasyOCR results get merged together upstream.

    y_tolerance_ratio controls how close two words' vertical centers must
    be (relative to word height) to be considered the same line.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w.bbox.y + w.bbox.height / 2))
    lines: list[list[OcrWord]] = []

    for word in sorted_words:
        word_cy = word.bbox.y + word.bbox.height / 2
        placed = False
        for line in lines:
            ref = line[0]
            ref_cy = ref.bbox.y + ref.bbox.height / 2
            tolerance = max(ref.bbox.height, word.bbox.height) * y_tolerance_ratio
            if abs(word_cy - ref_cy) <= tolerance:
                line.append(word)
                placed = True
                break
        if not placed:
            lines.append([word])

    result: list[OcrLine] = []
    for line_words in lines:
        line_words.sort(key=lambda w: w.bbox.x)
        text_parts = []
        spans = []
        cursor = 0
        for i, w in enumerate(line_words):
            if i > 0:
                text_parts.append(" ")
                cursor += 1
            start = cursor
            text_parts.append(w.text)
            cursor += len(w.text)
            spans.append((start, cursor))
        full_text = "".join(text_parts)
        result.append(OcrLine(text=full_text, words=line_words, word_spans=spans))

    return result


def words_covering_span(line: OcrLine, start: int, end: int) -> list[OcrWord]:
    """Return the subset of a line's words whose character span overlaps
    the given [start, end) range in the line's reconstructed text."""
    covering = []
    for word, (w_start, w_end) in zip(line.words, line.word_spans):
        if w_end > start and w_start < end:
            covering.append(word)
    return covering


def union_bbox(words: list[OcrWord]) -> BoundingBox:
    """Compute the bounding box that spans all given words, used when a
    matched date phrase covers multiple word boxes."""
    x0 = min(w.bbox.x for w in words)
    y0 = min(w.bbox.y for w in words)
    x1 = max(w.bbox.x + w.bbox.width for w in words)
    y1 = max(w.bbox.y + w.bbox.height for w in words)
    dpi = words[0].bbox.page_dpi
    is_pdf_space = words[0].bbox.is_pdf_space
    return BoundingBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0, page_dpi=dpi, is_pdf_space=is_pdf_space)


def find_label_words(all_words: list[OcrWord], full_text_lines: list[str] | None = None) -> list[OcrWord]:
    """Scan all OCR words for ones that match (or are part of phrases that
    match) known date field labels like 'Inspection Date' or 'Valid From'.
    Uses simple case-insensitive substring matching, which is tolerant
    enough for the label list in config.DATE_FIELD_LABELS while remaining
    predictable and fast.
    """
    label_words: list[OcrWord] = []
    for word in all_words:
        lower = word.text.lower().strip(":").strip()
        for label in DATE_FIELD_LABELS:
            if lower == label or lower in label or label in lower:
                label_words.append(word)
                break
    return label_words
