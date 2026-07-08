"""
core/date_parser.py

Turns raw OCR text into normalized `date` objects. This is where every
supported date format gets recognized and disambiguated.

Supported formats:
    DD/MM/YYYY, MM/DD/YYYY, D/M/YYYY   (numeric, slash or dash separated)
    YYYY-MM-DD                          (ISO)
    6 June 2026 / June 6, 2026          (long form, day-first or month-first)

Ambiguity handling:
    A string like "03/04/2026" is genuinely ambiguous — it could be March
    4th or April 3rd. This module resolves ambiguity using config.
    AMBIGUOUS_DATE_DEFAULT ("MDY" by default per company preference), but
    if the numbers make one interpretation impossible (e.g. "15/03/2026"
    can only be day=15, month=3), it uses the only valid interpretation
    and marks `format_inferred=True` so the report can flag it as
    "format-inferred" rather than silently guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from dateutil import parser as dateutil_parser

from config import AMBIGUOUS_DATE_DEFAULT, MAX_PLAUSIBLE_YEAR, MIN_PLAUSIBLE_YEAR
from utils.logger import get_logger

logger = get_logger(__name__)

# Numeric date pattern: captures three groups of 1-4 digits separated by
# '/', '-', or '.'. Handles D/M/YYYY, DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD.
_NUMERIC_DATE_RE = re.compile(
    r"\b(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})\b"
)

# Long-form date pattern: "6 June 2026", "June 6, 2026", "6th June 2026"
_MONTH_NAMES = (
    "january|february|march|april|may|june|july|august|september|"
    "october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_LONGFORM_DATE_RE = re.compile(
    rf"\b(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\s+(\d{{4}})"
    rf"|({_MONTH_NAMES})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}}))\b",
    re.IGNORECASE,
)


@dataclass
class ParseResult:
    """Outcome of attempting to parse a single date candidate string."""
    normalized: Optional[date]
    format_inferred: bool
    ambiguous: bool


def _is_plausible_year(year: int) -> bool:
    return MIN_PLAUSIBLE_YEAR <= year <= MAX_PLAUSIBLE_YEAR


def _normalize_2digit_year(y: int) -> int:
    """Convert a 2-digit year to 4 digits using a sliding window
    (assume 00-49 -> 2000s, 50-99 -> 1900s). This is a standard heuristic;
    documents older than ~1950 are out of scope for this tool."""
    if y < 100:
        return 2000 + y if y < 50 else 1900 + y
    return y


def _try_numeric_date(match: re.Match) -> ParseResult:
    """Resolve a numeric D/M/Y-style match, handling ISO (YYYY-MM-DD),
    unambiguous cases, and genuinely ambiguous DD/MM vs MM/DD cases."""
    a, b, c = match.group(1), match.group(2), match.group(3)
    a_i, b_i, c_i = int(a), int(b), int(c)

    # Case 1: ISO format YYYY-MM-DD (first group is 4 digits)
    if len(a) == 4:
        year, month, day = a_i, b_i, c_i
        if _is_plausible_year(year) and 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return ParseResult(date(year, month, day), False, False)
            except ValueError:
                return ParseResult(None, False, False)
        return ParseResult(None, False, False)

    # Otherwise the year is the third group (2 or 4 digits), and the first
    # two groups are day/month in some order.
    year = _normalize_2digit_year(c_i)
    if not _is_plausible_year(year):
        return ParseResult(None, False, False)

    first_valid_as_month = 1 <= a_i <= 12
    second_valid_as_month = 1 <= b_i <= 12
    first_valid_as_day = 1 <= a_i <= 31
    second_valid_as_day = 1 <= b_i <= 31

    # Determine which interpretations are structurally possible.
    can_be_mdy = first_valid_as_month and second_valid_as_day  # a=month, b=day
    can_be_dmy = first_valid_as_day and second_valid_as_month  # a=day, b=month

    if can_be_mdy and can_be_dmy and a_i != b_i:
        # Truly ambiguous (e.g. 03/04/2026) -> use configured default,
        # flag as inferred + ambiguous so reviewers can double check.
        if AMBIGUOUS_DATE_DEFAULT == "MDY":
            month, day = a_i, b_i
        else:
            day, month = a_i, b_i
        try:
            return ParseResult(date(year, month, day), True, True)
        except ValueError:
            return ParseResult(None, False, False)

    elif can_be_mdy and not can_be_dmy:
        month, day = a_i, b_i
        try:
            return ParseResult(date(year, month, day), False, False)
        except ValueError:
            return ParseResult(None, False, False)

    elif can_be_dmy and not can_be_mdy:
        day, month = a_i, b_i
        # Only one interpretation is valid (e.g. 15/03/2026 can't be
        # month=15), so this isn't really "inferred" — it's forced.
        try:
            return ParseResult(date(year, month, day), False, False)
        except ValueError:
            return ParseResult(None, False, False)

    elif can_be_mdy and can_be_dmy and a_i == b_i:
        # e.g. 05/05/2026 - no ambiguity in outcome even though both
        # interpretations are structurally valid.
        try:
            return ParseResult(date(year, a_i, b_i), False, False)
        except ValueError:
            return ParseResult(None, False, False)

    return ParseResult(None, False, False)


def _try_longform_date(match: re.Match) -> ParseResult:
    """Resolve a long-form date like '6 June 2026' or 'June 6, 2026'.
    No ambiguity here since the month is named explicitly."""
    text = match.group(0)
    try:
        parsed = dateutil_parser.parse(text, fuzzy=True)
        if _is_plausible_year(parsed.year):
            return ParseResult(parsed.date(), False, False)
    except (ValueError, OverflowError):
        pass
    return ParseResult(None, False, False)


def find_date_candidates(text: str) -> list[tuple[str, int, int, ParseResult]]:
    """Scan a block of OCR text and return every date-like substring found,
    along with its character offsets and parse result.

    Returns a list of (matched_text, start_offset, end_offset, ParseResult).
    """
    results: list[tuple[str, int, int, ParseResult]] = []

    for match in _NUMERIC_DATE_RE.finditer(text):
        parsed = _try_numeric_date(match)
        results.append((match.group(0), match.start(), match.end(), parsed))

    for match in _LONGFORM_DATE_RE.finditer(text):
        parsed = _try_longform_date(match)
        results.append((match.group(0), match.start(), match.end(), parsed))

    return results


def parse_single_date_string(text: str) -> ParseResult:
    """Convenience wrapper for parsing a string that is expected to be
    exactly one date (e.g. a single OCR word/line already isolated by the
    field locator). Falls back to dateutil's general parser if neither
    regex matches, to catch edge-case formats gracefully."""
    text = text.strip()

    numeric_match = _NUMERIC_DATE_RE.search(text)
    if numeric_match:
        return _try_numeric_date(numeric_match)

    longform_match = _LONGFORM_DATE_RE.search(text)
    if longform_match:
        return _try_longform_date(longform_match)

    # Last resort: let dateutil have a go, but require it to have found
    # something that looks date-shaped (avoid false positives on plain
    # words, which fuzzy=True is prone to).
    try:
        parsed = dateutil_parser.parse(text, fuzzy=True)
        if _is_plausible_year(parsed.year) and any(ch.isdigit() for ch in text):
            return ParseResult(parsed.date(), False, False)
    except (ValueError, OverflowError):
        pass

    return ParseResult(None, False, False)
