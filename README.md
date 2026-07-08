# Date Range Validator

A Windows desktop application that scans PDFs and scanned images (printed
or handwritten), detects every date on the page using OCR, and flags any
date that falls outside a user-specified valid range — producing an
annotated PDF (red/yellow highlights) and a detailed Excel report.

---

## 1. Folder Structure

```
date_range_validator/
├── main.py                    # Application entry point
├── config.py                  # All tunable constants (thresholds, DPI, labels, etc.)
├── setup.bat                  # Windows: one-click first-time setup (no manual Python install needed)
├── run.bat                    # Windows: one-click launch after setup.bat has run once
├── build.spec                 # PyInstaller spec for building a Windows .exe (bundles Tesseract if TESSERACT_BUNDLE_DIR is set)
├── .github/workflows/
│   └── build-windows-exe.yml  # Builds a ready-to-run .exe in the cloud via GitHub Actions — see §2
├── requirements.txt           # Python dependencies
├── README.md                  # This file
│
├── gui/                        # --- Presentation layer (PySide6) ---
│   ├── main_window.py          # Main window: layout, event wiring, results table
│   ├── drag_drop_widget.py     # Drag-and-drop file input area
│   └── worker.py               # Background QThread that runs the scan without freezing the UI
│
├── core/                        # --- Business logic (no GUI, no I/O side effects beyond files) ---
│   ├── document_processor.py   # Loads PDFs/images, orchestrates OCR + date extraction per page
│   ├── ocr_engine.py            # Tesseract + EasyOCR wrappers, merging, label-proximity matching
│   ├── date_parser.py           # Regex + dateutil based date recognition and normalization
│   └── validator.py             # Compares detected dates against the user's range
│
├── export/                      # --- Output generation ---
│   ├── pdf_annotator.py         # Draws red/yellow highlight boxes and saves annotated PDFs
│   └── excel_exporter.py        # Builds the multi-sheet Excel report
│
└── utils/                       # --- Shared infrastructure ---
    ├── models.py                 # Shared dataclasses (DetectedDate, FileResult, ScanSummary, ...)
    └── logger.py                  # Rotating file + console logging setup
```

**Why this layout:** each folder is a layer that only depends on the ones
below it (`gui` → `core`/`export` → `utils`). `core` has no Qt imports at
all, which means the OCR/parsing/validation logic can be unit tested, run
from a script, or reused in a future CLI/network-batch tool without
touching the GUI.

---

## 2. Getting a Ready-to-Run .exe (no Python, no setup, for anyone)

This project includes a GitHub Actions workflow that builds a genuinely
double-click-ready `DateRangeValidator.exe` — with Tesseract-OCR bundled
directly inside it — on GitHub's own Windows cloud machines, for free.
You don't need a Windows PC, Python, or any command line to do this;
it's entirely done through a web browser.

1. Go to [github.com](https://github.com) and sign in (or create a free
   account — takes a minute).
2. Click the **+** icon (top right) → **New repository**. Give it any
   name, leave everything else default, click **Create repository**.
3. On the new repo's page, click **"uploading an existing file"** (or
   **Add file → Upload files**). Drag in every file and folder from this
   `date_range_validator` project — including the hidden `.github`
   folder, which is what contains the build instructions — and commit.
4. Click the **Actions** tab at the top of the repo. You should see
   "Build Windows Executable" already running (it starts automatically
   once the files are uploaded). If it's not running, click it in the
   left sidebar, then click **Run workflow**.
5. Wait 10–20 minutes for it to finish (it's genuinely compiling
   everything from scratch each time, including OCR libraries — this is
   normal). A green checkmark means it succeeded.
6. Click into the finished run, scroll down to **Artifacts**, and
   download **DateRangeValidator-Windows**. That's a `.zip` — extract
   it, and `DateRangeValidator.exe` inside is the finished program.
   Double-click it. Nothing else to install.

That `.exe` folder can be copied to any Windows PC and run as-is — it
doesn't need Python or Tesseract installed separately, since both are
bundled inside it. Share the whole extracted folder (not just the .exe
file alone) with anyone else who needs to run it, since the DLLs and
bundled Tesseract data sit alongside it.

If you'd rather run it from source or build it yourself locally instead,
see the alternatives below.

## 3. Alternative: Running from source

### Option A — Automated setup (no manual Python install)

This uses a private, portable copy of Python stored only inside this
project folder — it does not touch or require any Python already on
your system, and needs no admin rights for that part.

1. Copy the whole `date_range_validator` folder anywhere on your PC.
2. Double-click **`setup.bat`**. Leave it running — first-time setup
   downloads a portable Python, installs the required packages
   (EasyOCR pulls in PyTorch, which is a large download, so this can
   take 10+ minutes depending on your connection), and downloads/launches
   the official Tesseract-OCR installer for you to click through once
   (Windows will ask you to confirm this install, same as any other
   program — the default options in that installer are fine).
3. Once setup finishes, double-click **`run.bat`** any time to launch
   the app. That's it — no command line, no typing.

If setup.bat fails partway (e.g. your connection drops), just run it
again — it skips any step it already completed.

### Option B — Manual install (more control, or if you already use Python)

#### Step 1 — Install Python
Install Python 3.11 or 3.12 (64-bit) from [python.org](https://www.python.org/downloads/).
During setup, check **"Add python.exe to PATH."**

#### Step 2 — Install Tesseract OCR
This app uses free/offline OCR, which requires the Tesseract binary
separately (it is not a Python package):

1. Download the Windows installer from the
   [UB-Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki)
   (the most commonly used Windows build).
2. Install it (default path is `C:\Program Files\Tesseract-OCR`).
3. If you skip adding it to PATH during install, set an environment
   variable so the app can find it:
   ```
   setx TESSERACT_CMD "C:\Program Files\Tesseract-OCR\tesseract.exe"
   ```
   (Restart your terminal/IDE after running this.)

#### Step 3 — Get the project files
Copy the `date_range_validator/` folder to your machine.

#### Step 4 — Install Python dependencies
Open a terminal in the project folder and run:

```bash
pip install -r requirements.txt
```

> **Note on EasyOCR:** EasyOCR depends on PyTorch, which is a large
> download (500 MB+) the first time. This is expected — EasyOCR is the
> component responsible for the handwriting-recognition uplift over
> Tesseract alone. If you want the lightest possible install and only
> care about printed text, you can remove `easyocr` from
> `requirements.txt`; the app will log a warning per page and continue
> using Tesseract-only results.

#### Step 5 — Run the application

```bash
python main.py
```

#### Step 6 (optional) — Build a standalone .exe
So end users don't need Python installed at all:

```bash
pip install pyinstaller
pyinstaller build.spec
```

The finished app will be in `dist/DateRangeValidator/DateRangeValidator.exe`.
See the comments in `build.spec` for how to bundle Tesseract itself into
that folder so target machines don't need it installed separately.

---

## 4. Dependency List

| Library | Purpose |
|---|---|
| PySide6 | Desktop GUI framework |
| pytesseract | Python wrapper for Tesseract OCR (printed text, fast) |
| easyocr | Deep-learning OCR (better on handwriting/stylized text) |
| opencv-python-headless | Image preprocessing: denoise, threshold, deskew |
| Pillow | Image loading (JPG/PNG/TIFF), multi-frame TIFF support |
| PyMuPDF (fitz) | PDF rendering to images, PDF annotation, image→PDF conversion, image-object detection |
| pdfplumber | Direct text-layer extraction for born-digital PDF pages (fast path that skips OCR entirely — see §4) |
| python-dateutil | Fallback fuzzy date parsing |
| openpyxl | Excel (.xlsx) report generation with styling |
| numpy | Array handling for OpenCV/image processing |

---

## 5. How It Works (Architecture)

1. **Input** — User adds files via drag-and-drop or the file browser.
   Supported: PDF, JPG, JPEG, PNG, TIFF (including multi-page TIFF).

2. **Per-file processing** (`core/document_processor.py`), run in
   parallel across files using `ProcessPoolExecutor` (real multi-core
   parallelism, since OCR is CPU-bound):
   - Each PDF page is checked for an embedded raster image
     (`PyMuPDF`'s `get_images`). Pages with **zero** embedded images are
     genuinely "born digital" (e.g. exported straight from Word/Excel)
     and cannot physically contain handwriting, so the app reads dates
     directly from the PDF's text layer (`pdfplumber`) at 100% confidence
     and **skips OCR entirely** for that page — faster and exact.
   - **Any page with an embedded image is always fully OCR'd**, even if
     it also carries its own text layer. This matters because many office
     scanners produce "searchable PDF" output that bakes in the
     scanner's *own* OCR as an invisible text layer over the scanned
     image — and that baked-in layer can look perfectly healthy (plenty
     of characters) while having completely missed a handwritten
     fill-in, since scanner-side OCR essentially never reads handwriting.
     Trusting a text layer just because it's long enough would silently
     defeat the whole point of this app on exactly the documents it's
     meant for. So the rule is deliberately simple and conservative: any
     embedded image at all → full dual-engine OCR, no exceptions.
   - For pages that need OCR: rasterize to an image at 300 DPI
     (`PyMuPDF`), then preprocess (`core/ocr_engine.py`): grayscale →
     denoise → adaptive threshold → **deskew** (auto-detects and corrects
     the slight rotation common in paper scans).
   - **Both** Tesseract and EasyOCR run on every OCR'd page. Their
     word-level detections are merged: where both engines found the same
     region, the higher-confidence read wins; where only one engine found
     something, it's kept. This dual-engine approach exists specifically
     because Tesseract is fast but weak on handwriting, while EasyOCR is
     slower but meaningfully better at it — running both and merging
     gets the best of each rather than betting on one engine's blind
     spots.
   - Words (from OCR, or from a text-layer page) are regrouped into lines
     (by vertical proximity) so multi-word date phrases like "June 6,
     2026" are caught correctly, not just single-token dates like
     "06/15/2026".
   - **Date recognition** (`core/date_parser.py`) matches numeric formats
     (`DD/MM/YYYY`, `MM/DD/YYYY`, `D/M/YYYY`, `YYYY-MM-DD`) and long-form
     dates (`6 June 2026`, `June 6, 2026`).
   - **Field location** — instead of fixed coordinates, the app looks for
     OCR text matching known field labels (`Date`, `Inspection Date`,
     `Valid From`, etc. — see `config.DATE_FIELD_LABELS`) and attributes
     the nearest date to that label. This is what lets it work across
     different document templates without per-template configuration.
   - A single bad page (corrupt image data, a render failure, etc.) is
     isolated to that page — it's recorded as a page-level error and the
     rest of the file still processes normally, rather than aborting the
     whole document.

3. **Ambiguous date handling** — A string like `03/04/2026` is genuinely
   ambiguous (March 4 vs. April 3). Per your configuration, the app
   defaults to **MM/DD/YYYY** in ambiguous cases (`config.AMBIGUOUS_DATE_DEFAULT`),
   but if the numbers make one interpretation impossible (e.g. `15/03/2026`
   can only be day=15, month=3), it uses the only valid reading and does
   **not** mark it as inferred, since there was no actual ambiguity. Dates
   where a real guess was made are flagged `Format Inferred = Yes` in the
   Excel report so they're easy to spot-check.

4. **Validation** (`core/validator.py`) — every detected date is compared
   to the user's start/end range:
   - **Below 80% OCR confidence → "Needs Manual Review"** (yellow),
     regardless of whether the parsed value happens to be in range. A
     low-confidence read is not trustworthy even if it looks fine.
   - Otherwise: inside the range → **Valid**; outside → **Out of Range** (red).

5. **Output**:
   - **Annotated PDF** (`export/pdf_annotator.py`) — a copy of each
     document with red rectangles around out-of-range dates and yellow
     rectangles around needs-review dates, as real (searchable, not
     rasterized) PDF annotations.
   - **Excel report** (`export/excel_exporter.py`) — a "Summary" sheet
     (files/pages/dates scanned, out-of-range count, review count,
     average confidence, processing time) and a "Date Details" sheet
     with one row per detected date (file, page, raw text, normalized
     date, status, confidence, nearby label, whether the format was
     inferred, which OCR engine won), color-coded by status, with
     autofilter enabled for easy sorting in Excel.

---

## 6. Known Limitations (please read before relying on this in production)

- **Handwriting accuracy is inherently limited with free/offline OCR.**
  Tesseract and EasyOCR are good, but real handwriting recognition
  accuracy is meaningfully lower than printed text. That's exactly what
  the confidence threshold and "Needs Manual Review" bucket are for — treat
  yellow-flagged items as "a human should look at this," not as an error.
  If handwriting accuracy becomes business-critical, the natural next
  step is swapping in a cloud OCR engine (Azure Document Intelligence,
  Google Vision, AWS Textract all handle handwriting noticeably better),
  which would be a contained change to `core/ocr_engine.py` only.
- **"Every date on the page" includes incidental dates** — a stray
  printed form date or stamp near a label can get attributed to that
  label. The label-proximity distance is tunable in
  `config.LABEL_PROXIMITY_PX`.
- **Performance** scales with page count and CPU cores, not file count
  alone; hundreds of multi-page scanned PDFs on a standard office PC
  (no GPU) should be expected to take real wall-clock time — this is a
  batch job, not an instant operation. `config.MAX_WORKERS` controls
  parallelism.
- **The digital-text fast path is deliberately conservative.** Any page
  with so much as a letterhead logo image on it will take the full OCR
  path rather than the instant text-layer path, even though the rest of
  the page is ordinary typed text. This trades away some speed on
  logo-bearing digital documents in exchange for never silently trusting
  a scanner's own baked-in OCR layer over a page that might actually
  contain a handwritten fill-in. If most of your born-digital documents
  carry a small logo and you want the speed back, the check in
  `core.document_processor._page_has_embedded_image` could be refined to
  ignore images below a certain size — this wasn't done by default
  because it reintroduces a small chance of misclassifying a scan.

---

## 7. Future Expansion

The architecture was built so these can be added without restructuring:

- **Company-specific templates** — `config.DATE_FIELD_LABELS` is already
  the single place new label vocabulary would go; a template-confidence
  layer could be added in `core/ocr_engine.py` alongside the existing
  label matcher.
- **Barcode / QR code detection** — would slot in as a new function in
  `core/ocr_engine.py` (OpenCV has built-in barcode/QR detectors), feeding
  into a new field on `PageResult`.
- **Automatic document classification** — a new module under `core/`
  (e.g. `core/classifier.py`) consuming the same OCR word list already
  produced per page.
- **Signature detection** — similarly a new `core/` module operating on
  the same preprocessed page image.
- **Cloud storage / network folder batch processing** — `core/document_processor.process_file`
  already takes a plain file path; a new `core/batch_source.py` could
  enumerate files from S3/SharePoint/a network share and feed the same
  pipeline, with no changes needed to OCR/parsing/validation/export.
- **Microsoft Excel integration** (e.g. writing into an existing company
  workbook/template rather than a fresh file) — would extend
  `export/excel_exporter.py`.

---

## 8. Logging

All runs are logged to a rotating log file at:
```
%USERPROFILE%\DateRangeValidator_Output\logs\date_range_validator.log
```
(5 MB per file, 5 backups kept) — useful for diagnosing OCR failures or
reviewing what was processed, for audit purposes in a business setting.
