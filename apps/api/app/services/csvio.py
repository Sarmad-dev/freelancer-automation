"""CSV reading and writing with the edge cases that matter for user-supplied files.

Reading: BOM, any of CRLF/LF/CR line endings, quoted fields containing delimiters, quotes and newlines,
comma / semicolon / tab / pipe delimiters, blank lines, short and long rows, duplicate or empty headers, and
size limits. Writing: neutralises spreadsheet formulas ("CSV injection") in every cell.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

MAX_CHARS = 2_000_000
MAX_ROWS = 5_000
MAX_COLUMNS = 60
MAX_CELL = 2_000
DELIMITERS = (",", ";", "\t", "|")

_FORMULA = re.compile(r"^[=+\-@\t\r]")
_PHONE_LIKE = re.compile(r"^\+[0-9][0-9 ().\-]*$")


class CsvProblem(ValueError):
    """The file as a whole cannot be used. The message is written for the person who chose the file."""


@dataclass
class ParsedCsv:
    headers: list[str]
    rows: list[list[str]]  # trimmed cells, padded to len(headers); blank lines already dropped
    row_numbers: list[int]  # 1-based line number in the file (header = 1) for each kept row
    delimiter: str
    extra_cells: dict[int, int] = field(
        default_factory=dict
    )  # row number -> cells beyond the header


def safe_cell(value: object) -> str:
    """Neutralise formula injection: a cell that would start a formula in a spreadsheet is prefixed with '."""
    text = "" if value is None else str(value)
    if _FORMULA.match(text) and not _PHONE_LIKE.match(text):
        return "'" + text
    return text


def to_csv(header: list[str], rows: list[list[object]], *, bom: bool = True) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([safe_cell(h) for h in header])
    for row in rows:
        writer.writerow([safe_cell(c) for c in row])
    return ("﻿" if bom else "") + buffer.getvalue()


def _detect_delimiter(first_line: str) -> str:
    best, best_count = ",", 0
    for candidate in DELIMITERS:
        count = first_line.count(candidate)
        if count > best_count:
            best, best_count = candidate, count
    return best


def parse(content: str) -> ParsedCsv:
    if "\x00" in content:
        raise CsvProblem("This doesn't look like a text CSV file.")
    text = content.lstrip("﻿")
    if len(text) > MAX_CHARS:
        raise CsvProblem("The file is too large. Split it into files under 2 MB.")
    if not text.strip():
        raise CsvProblem("The file is empty.")
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    delimiter = _detect_delimiter(first_line)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    headers: list[str] | None = None
    rows: list[list[str]] = []
    numbers: list[int] = []
    extras: dict[int, int] = {}
    previous = 0
    try:
        for record in reader:
            line = previous + 1  # first physical line of this record (quoted values may span lines)
            previous = reader.line_num
            if headers is None:
                if not any(c.strip() for c in record):
                    continue
                headers = [c.strip() for c in record]
                if len(headers) > MAX_COLUMNS:
                    raise CsvProblem(f"Too many columns (the limit is {MAX_COLUMNS}).")
                continue
            if not any(c.strip() for c in record):
                continue  # blank line
            if len(rows) >= MAX_ROWS:
                raise CsvProblem(f"Too many rows. Import at most {MAX_ROWS:,} rows at a time.")
            cells = [c.strip() for c in record]
            if len(cells) > len(headers):
                extras[line] = len(cells) - len(headers)
                cells = cells[: len(headers)]
            cells += [""] * (len(headers) - len(cells))
            rows.append(cells)
            numbers.append(line)
    except csv.Error as exc:
        raise CsvProblem(
            "The file isn't valid CSV: a quoted value is not closed or is too long."
        ) from exc
    if headers is None:
        raise CsvProblem("The file has no header row.")
    named = [h for h in headers if h]
    if not named:
        raise CsvProblem("The header row has no column names.")
    folded = [h.casefold() for h in named]
    if len(set(folded)) != len(folded):
        raise CsvProblem("Two columns have the same name. Rename them and try again.")
    if not rows:
        raise CsvProblem("The file has a header but no data rows.")
    return ParsedCsv(
        headers=headers, rows=rows, row_numbers=numbers, delimiter=delimiter, extra_cells=extras
    )
