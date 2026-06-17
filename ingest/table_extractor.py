"""
Financial Table Extractor (Phase 3)

Why this matters
----------------
Standard RAG chunks prose and loses table structure entirely — a row like
  "Net revenue | 383,285 | 394,328 | 365,817"
gets split across chunks or ingested as unstructured text, making numeric
verification probabilistic.

This module extracts tables separately using pdfplumber, normalises each row
into typed records {line_item, value, year, page}, and stores them in SQLite.
The cross-verifier can then do an exact lookup before falling back to LLM.

Extraction strategy
-------------------
pdfplumber detects table borders/whitespace heuristically. For Apple 10-Ks
(and most SEC filings) this covers:
  - Consolidated Statements of Operations (income statement)
  - Consolidated Balance Sheets
  - Consolidated Statements of Cash Flows
  - Product segment revenue tables

Value normalisation handles:
  - Leading/trailing whitespace and $ signs
  - Parenthesis-as-negative accounting notation: (1,234) → -1234
  - Comma thousands separators
  - Blank / header-only rows
  - Multi-year column headers (2023, 2022, 2021)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pdfplumber

from database.models import FinancialRecord
from database.session import SessionLocal


# ---------------------------------------------------------------------------
# Data class (in-memory before DB write)
# ---------------------------------------------------------------------------

@dataclass
class ExtractedRecord:
    doc_id:      str
    line_item:   str          # original text from PDF
    value:       float        # numeric, in units stated on page (usually millions)
    unit:        str          # "millions" | "thousands" | "per share" | "unknown"
    year:        int
    source_page: int
    table_type:  str          # "income_statement" | "balance_sheet" | "cash_flow" | "segment" | "unknown"


# ---------------------------------------------------------------------------
# Table-type heuristics
# ---------------------------------------------------------------------------

_TABLE_TYPE_PATTERNS = [
    ("income_statement", re.compile(
        r"(net revenue|net sales|operating income|net income|earnings per share|"
        r"cost of sales|gross margin|research and development)", re.I)),
    ("balance_sheet", re.compile(
        r"(total assets|total liabilities|shareholders.{0,10}equity|"
        r"cash and cash equivalents|accounts receivable|inventories)", re.I)),
    ("cash_flow", re.compile(
        r"(operating activities|investing activities|financing activities|"
        r"capital expenditures|depreciation|free cash flow)", re.I)),
    ("segment", re.compile(
        r"(iphone|mac|ipad|wearables|services|americas|europe|greater china|"
        r"japan|rest of asia)", re.I)),
]


def _classify_table(rows: list[list[str | None]]) -> str:
    text = " ".join(
        cell for row in rows for cell in row if cell
    )
    for table_type, pat in _TABLE_TYPE_PATTERNS:
        if pat.search(text):
            return table_type
    return "unknown"


# ---------------------------------------------------------------------------
# Year detection
# ---------------------------------------------------------------------------

def _years_from_headers(headers: list[str | None]) -> dict[int, int]:
    """Return {col_index: year} for header cells that contain a 4-digit year."""
    year_pat = re.compile(r"\b(20\d{2})\b")
    result: dict[int, int] = {}
    for i, h in enumerate(headers):
        if not h:
            continue
        m = year_pat.search(str(h))
        if m:
            result[i] = int(m.group(1))
    return result


def _years_from_text(page_text: str) -> list[int]:
    """
    Extract ordered list of fiscal years from prose like
    "for 2023, 2022 and 2021 were as follows".
    Returns e.g. [2023, 2022, 2021] (first-mention order = most-recent first).
    """
    # Find all 20xx years that appear in the page text in order
    found: list[int] = []
    seen: set[int] = set()
    for m in re.finditer(r"\b(20\d{2})\b", page_text):
        yr = int(m.group(1))
        if yr not in seen:
            seen.add(yr)
            found.append(yr)
    return found


def _detect_value_columns(table: list[list[str | None]]) -> list[int]:
    """
    Find column indices that contain numeric data in at least 30% of rows.
    Skips column 0 (assumed to be the line-item label).
    """
    if not table:
        return []
    ncols = max(len(r) for r in table)
    num_counts = [0] * ncols
    for row in table:
        for ci, cell in enumerate(row):
            if ci == 0:
                continue
            if _parse_value(cell) is not None:
                num_counts[ci] += 1
    threshold = max(1, len(table) * 0.3)
    return [ci for ci, cnt in enumerate(num_counts) if cnt >= threshold]


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------

def _parse_value(raw: str | None) -> float | None:
    if not raw:
        return None
    s = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not s or s in ("-", "—", "–", "*", "**"):
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def _detect_unit(page_text: str) -> str:
    if re.search(r"in millions", page_text, re.I):
        return "millions"
    if re.search(r"in thousands", page_text, re.I):
        return "thousands"
    if re.search(r"in billions", page_text, re.I):
        return "billions"
    return "millions"  # SEC filings almost always report in millions


def _normalize_line_item(text: str) -> str:
    """Lowercase, collapse whitespace, strip leading punctuation/spaces."""
    t = re.sub(r"\s+", " ", text.lower().strip())
    t = t.lstrip(":•–—-").strip()
    return t


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def _build_year_col_map(
    table: list[list[str | None]],
    page_years: list[int],
) -> dict[int, int]:
    """
    Return {col_index: year} using two strategies:
      1. Year in column header (e.g. "2023")
      2. Year in page text + positional assignment to value columns
    """
    # Strategy 1: years in headers
    from_headers = _years_from_headers(table[0]) if table else {}
    if from_headers:
        return from_headers

    # Strategy 2: map page years to value columns positionally
    val_cols = _detect_value_columns(table)
    if not val_cols or not page_years:
        return {}
    # Pair up: first value column → first year (most recent), etc.
    return {col: yr for col, yr in zip(val_cols, page_years)}


def extract_tables_from_pdf(pdf_path: str, doc_id: str) -> list[ExtractedRecord]:
    """
    Extract all financial table rows from a PDF.

    Two-pass year detection:
      - If table headers contain years (e.g. "September 2023") → use those
      - Otherwise pull years from page prose and assign positionally to
        the value columns (SEC filings always list most-recent year first)
    """
    records: list[ExtractedRecord] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            unit       = _detect_unit(page_text)
            page_years = _years_from_text(page_text)

            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                if not table or len(table) < 2:
                    continue

                year_col_map = _build_year_col_map(table, page_years)
                if not year_col_map:
                    continue

                table_type = _classify_table(table)

                for row in table:
                    if not row or not row[0]:
                        continue
                    line_item = str(row[0]).strip()
                    if not line_item or len(line_item) < 3:
                        continue
                    # Skip rows that are all-non-numeric (header/divider/label)
                    if all(_parse_value(row[ci]) is None for ci in year_col_map):
                        continue

                    for col_idx, year in year_col_map.items():
                        if col_idx >= len(row):
                            continue
                        value = _parse_value(row[col_idx])
                        if value is None:
                            continue
                        records.append(ExtractedRecord(
                            doc_id=doc_id,
                            line_item=line_item,
                            value=value,
                            unit=unit,
                            year=year,
                            source_page=page_num,
                            table_type=table_type,
                        ))

    return records


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def store_financial_records(records: list[ExtractedRecord], doc_id: str) -> int:
    """
    Upsert extracted records for a doc_id.
    Deletes existing records for the doc first (re-index is idempotent).
    Returns count of rows written.
    """
    with SessionLocal() as db:
        db.query(FinancialRecord).filter_by(doc_id=doc_id).delete()
        for r in records:
            db.add(FinancialRecord(
                doc_id=r.doc_id,
                line_item=r.line_item,
                line_item_normalized=_normalize_line_item(r.line_item),
                value=r.value,
                unit=r.unit,
                year=r.year,
                source_page=r.source_page,
                table_type=r.table_type,
            ))
        db.commit()
    return len(records)


# ---------------------------------------------------------------------------
# Structured lookup (used by cross-verifier)
# ---------------------------------------------------------------------------

# Maps the cross-verifier's metric labels to line-item substrings to search
METRIC_KEYWORDS: dict[str, list[str]] = {
    "revenue":          ["total net sales", "net revenue", "net sales", "total revenue"],
    "net_income":       ["net income", "net earnings"],
    "gross_profit":     ["gross margin", "gross profit"],
    "operating_profit": ["operating income", "income from operations"],
    "ebitda":           ["ebitda"],
    "eps":              ["diluted", "earnings per share"],
    # balance sheet line items vary by company; cover common forms
    "total_assets":     ["total assets", "total current assets", "total non-current assets"],
    "total_debt":       ["term debt", "long-term debt", "total debt", "notes payable"],
    "cash":             ["cash and cash equivalents", "cash, cash equivalents",
                        "cash equivalents", "marketable securities"],
}


_NOISE_PREFIXES = (
    "percentage", "percent", "adjustment", "change in",
    "increase in", "decrease in", "effect of", "reconciliation",
    "less:", "add:", "less ", "total change",
)

def lookup_structured(
    metric: str,
    year: int,
    doc_id: str,
    tolerance: float = 0.01,
) -> float | None:
    """
    Return the authoritative value for (metric, year, doc_id) from the
    financial_records table, or None if not found.

    Lookup strategy:
      1. Filter by doc_id + year + keyword substring
      2. Exclude known noise rows (percentages, adjustments, change-in rows)
      3. Prefer income_statement / balance_sheet typed rows
      4. Order by abs(value) DESC — totals are larger than subtotals/components
      5. First result wins
    """
    from sqlalchemy import case, func as sqlfunc
    keywords = METRIC_KEYWORDS.get(metric, [metric.replace("_", " ")])
    preferred_types = {"income_statement", "balance_sheet", "segment"}

    with SessionLocal() as db:
        for kw in keywords:
            q = (
                db.query(FinancialRecord)
                .filter(
                    FinancialRecord.doc_id == doc_id,
                    FinancialRecord.year == year,
                    FinancialRecord.line_item_normalized.contains(kw),
                )
            )
            rows = q.all()
            if not rows:
                continue

            # Exclude noise rows
            clean = [
                r for r in rows
                if not any(r.line_item_normalized.startswith(p) for p in _NOISE_PREFIXES)
            ]
            if not clean:
                clean = rows  # fall back if exclusion removed everything

            # Prefer typed rows, then sort by abs(value) DESC
            typed   = [r for r in clean if r.table_type in preferred_types]
            ordered = sorted(typed or clean, key=lambda r: abs(r.value), reverse=True)
            if ordered:
                return ordered[0].value

    return None


def get_all_records(doc_id: str) -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.query(FinancialRecord)
            .filter_by(doc_id=doc_id)
            .order_by(FinancialRecord.table_type, FinancialRecord.year.desc(),
                      FinancialRecord.line_item_normalized)
            .all()
        )
        return [r.to_dict() for r in rows]
