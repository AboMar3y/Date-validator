"""
export/pdf_annotator.py

Produces an annotated copy of each scanned PDF (or an image converted to
a single-page PDF) with colored rectangles drawn around out-of-range
dates (red) and low-confidence dates needing manual review (yellow).

Uses PyMuPDF (fitz) for both reading the original PDF structure and
drawing annotations, since it can add real vector annotations rather
than baking highlights into a raster, keeping the output text-searchable
and print-quality.
"""

from __future__ import annotations

import os
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

from config import HIGHLIGHT_COLOR_INVALID, HIGHLIGHT_COLOR_REVIEW
from utils.logger import get_logger
from utils.models import FileResult, ValidationStatus

logger = get_logger(__name__)


def _image_file_to_pdf(file_path: str) -> fitz.Document:
    """Convert a standalone image file (JPG/PNG/TIFF) into an in-memory
    single- or multi-page PDF so it can be annotated the same way as a
    native PDF. TIFF multi-frame files become multi-page PDFs."""
    pil_img = Image.open(file_path)
    frame_count = getattr(pil_img, "n_frames", 1)

    doc = fitz.open()
    for i in range(frame_count):
        pil_img.seek(i)
        rgb = pil_img.convert("RGB")
        # PyMuPDF can insert an image directly as a new page sized to it.
        w, h = rgb.size
        page = doc.new_page(width=w, height=h)
        # Encode to PNG bytes in memory for insertion.
        import io
        buf = io.BytesIO()
        rgb.save(buf, format="PNG")
        page.insert_image(page.rect, stream=buf.getvalue())
    return doc


def annotate_file(file_result: FileResult, output_path: str) -> tuple[Optional[str], bool]:
    """Create an annotated PDF for one processed file.

    Returns a (output_path, any_highlighted) tuple. output_path is None
    only if the file could not be opened at all; otherwise the annotated
    copy is always written (even with zero highlights, for consistency),
    and any_highlighted tells the caller whether it actually contains any
    red/yellow markup, which is useful for batch-level reporting (e.g.
    "12 of 40 files had at least one flagged date").

    Only OUT_OF_RANGE (red) and NEEDS_REVIEW (yellow) dates are drawn;
    VALID dates are intentionally left unmarked to keep the visual focus
    on what needs attention, consistent with the requirement to
    "highlight any date that falls outside the range."
    """
    if file_result.error:
        logger.info("Skipping annotation for %s due to earlier error: %s",
                     file_result.file_name, file_result.error)
        return None, False

    ext = os.path.splitext(file_result.file_path)[1].lower()
    try:
        if ext == ".pdf":
            doc = fitz.open(file_result.file_path)
        else:
            doc = _image_file_to_pdf(file_result.file_path)
    except Exception as exc:
        logger.error("Could not open %s for annotation: %s", file_result.file_name, exc)
        return None, False

    any_highlight = False
    try:
        for page_result in file_result.pages:
            if page_result.page_number - 1 >= len(doc):
                continue
            page = doc[page_result.page_number - 1]

            for detected in page_result.dates:
                if detected.status not in (ValidationStatus.OUT_OF_RANGE, ValidationStatus.NEEDS_REVIEW):
                    continue

                rect_coords = detected.bbox.to_pdf_rect(
                    page.rect.width, page.rect.height,
                    page_result.image_width_px, page_result.image_height_px,
                )
                rect = fitz.Rect(*rect_coords)
                # Add a small margin so the box doesn't clip tight text.
                rect = rect + (-2, -2, 2, 2)

                color = (
                    HIGHLIGHT_COLOR_INVALID
                    if detected.status == ValidationStatus.OUT_OF_RANGE
                    else HIGHLIGHT_COLOR_REVIEW
                )
                annot = page.add_rect_annot(rect)
                annot.set_colors(stroke=color)
                annot.set_border(width=2)
                label_bits = [detected.display_date]
                if detected.nearby_label:
                    label_bits.append(f"({detected.nearby_label})")
                label_bits.append(detected.status.value)
                annot.set_info(content=" ".join(label_bits))
                annot.update()
                any_highlight = True

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        doc.save(output_path)
    finally:
        doc.close()

    return output_path, any_highlight


def annotate_all_files(file_results: list[FileResult], output_dir: str) -> dict[str, str]:
    """Annotate every file in a batch, writing each to output_dir with an
    '_annotated' suffix. Returns a dict mapping original file_name to the
    output path, skipping files that failed to load in the first place.
    """
    os.makedirs(output_dir, exist_ok=True)
    outputs: dict[str, str] = {}
    for file_result in file_results:
        if file_result.error:
            continue
        base_name = os.path.splitext(file_result.file_name)[0]
        out_path = os.path.join(output_dir, f"{base_name}_annotated.pdf")
        result_path, _any_highlight = annotate_file(file_result, out_path)
        if result_path:
            outputs[file_result.file_name] = result_path
    return outputs
