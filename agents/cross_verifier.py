"""
Cross-Verification Agent

Groups claims by financial metric keywords, then for each group with ≥2 claims
calls an LLM to check numeric consistency and emit a VerificationResult.

Groups with only one claim are skipped — nothing to cross-check.
"""

from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from graph.state import Claim, VerificationResult
from ingest.table_extractor import lookup_structured

MAX_GROUPS = 4  # cap parallel LLM calls; rare to have more meaningful groups

# Relative tolerance for structured numeric comparison (1% = rounding ok)
_NUMERIC_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Metric keyword groups (order matters: first match wins)
# ---------------------------------------------------------------------------

_METRIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("revenue",       re.compile(r"\b(revenue|turnover|sales)\b", re.I)),
    ("net_income",    re.compile(r"\b(net income|net profit|pat|profit after tax)\b", re.I)),
    ("ebitda",        re.compile(r"\bebitda\b", re.I)),
    ("eps",           re.compile(r"\b(eps|earnings per share)\b", re.I)),
    ("gross_profit",  re.compile(r"\b(gross profit|gross margin)\b", re.I)),
    ("total_assets",  re.compile(r"\btotal assets\b", re.I)),
    ("total_debt",    re.compile(r"\b(total debt|borrowings)\b", re.I)),
    ("cash",          re.compile(r"\b(cash and cash equivalents|cash flow)\b", re.I)),
    ("operating_profit", re.compile(r"\b(operating profit|ebit|pbit)\b", re.I)),
]


# ---------------------------------------------------------------------------
# Pydantic response model
# ---------------------------------------------------------------------------

class VerificationModel(BaseModel):
    status: str = Field(description="'consistent' if values agree, 'warning' if they differ or are ambiguous.")
    reason: str = Field(description="Explanation of why claims are consistent or inconsistent.")
    difference: str | None = Field(
        default=None,
        description="If inconsistent, describe the numeric difference (e.g. '₹120 Cr vs ₹118 Cr'). Null if consistent.",
    )


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial auditor checking for consistency across sections of a financial report. \
You will receive two or more claims about the same financial metric. \
Determine whether they report the same value, and flag any numeric discrepancy. \
Be precise about numbers — rounding differences under 1% can be marked consistent."""


def verify_claims(
    claims: list[Claim],
    llm: ChatOpenAI,
) -> list[VerificationResult]:
    """
    Cross-check claims about the same metric across different pages/sections.

    Phase 3 upgrade — two-tier verification:
      Tier 1 (structured): query financial_records table for the metric + year.
                           If a DB value exists, compare numerically — zero LLM calls,
                           100% deterministic, <1ms.
      Tier 2 (LLM):        fall back to LLM pairwise consistency check when no
                           structured record exists (e.g. risk-factor claims, ratios).

    This split is the key interview talking point: "Structured verification is an
    exact lookup. LLM verification is probabilistic. We always prefer the former."
    """
    structured_llm = llm.with_structured_output(VerificationModel, method="function_calling")
    groups = _group_by_metric(claims)

    # Only groups with ≥2 claims need checking; cap at MAX_GROUPS
    checkable = [(m, g) for m, g in groups.items() if len(g) >= 2][:MAX_GROUPS]

    if not checkable:
        return []

    def _check_one(metric: str, group_claims: list[Claim]) -> VerificationResult:
        # ── Tier 1: structured lookup ────────────────────────────────────────
        # Extract year from claim text (e.g. "for FY2023" → 2023)
        year = _extract_year(group_claims)
        doc_id = group_claims[0]["source_doc"]

        if year:
            db_value = lookup_structured(metric, year, doc_id)
            if db_value is not None:
                # Compare each claim's numeric value against the DB record
                mismatches = []
                for c in group_claims:
                    claim_val = _extract_numeric(c["claim"])
                    if claim_val is None:
                        continue
                    rel_diff = abs(claim_val - db_value) / max(abs(db_value), 1)
                    if rel_diff > _NUMERIC_TOLERANCE:
                        mismatches.append(
                            f"claim={claim_val:,.0f} vs table={db_value:,.0f} "
                            f"({rel_diff:.1%} diff)"
                        )

                if mismatches:
                    return VerificationResult(
                        metric=metric,
                        status="warning",
                        reason=f"[STRUCTURED] Claim value differs from extracted table data: "
                               + "; ".join(mismatches),
                        difference=mismatches[0],
                        supporting_claims=group_claims,
                    )
                else:
                    return VerificationResult(
                        metric=metric,
                        status="consistent",
                        reason=f"[STRUCTURED] Claim value matches financial_records table "
                               f"(db={db_value:,.0f}, year={year}).",
                        difference=None,
                        supporting_claims=group_claims,
                    )

        # ── Tier 2: LLM fallback ─────────────────────────────────────────────
        claim_text = "\n".join(
            f"- [Doc: {c['source_doc']} | Page {c['source_page']}] {c['claim']}"
            for c in group_claims
        )
        user_msg = (
            f"Metric: {metric.replace('_', ' ').title()}\n\n"
            f"Claims from different parts of the document:\n{claim_text}\n\n"
            "Are these claims numerically consistent?"
        )
        response = structured_llm.invoke(
            [{"role": "system", "content": _SYSTEM_PROMPT},
             {"role": "user", "content": user_msg}]
        )
        if isinstance(response, dict):
            status     = response.get("status", "warning")
            reason     = "[LLM] " + response.get("reason", "")
            difference = response.get("difference")
        else:
            status     = response.status
            reason     = "[LLM] " + response.reason
            difference = response.difference
        return VerificationResult(
            metric=metric,
            status=status if status in ("consistent", "warning") else "warning",
            reason=reason,
            difference=difference,
            supporting_claims=group_claims,
        )

    results: list[VerificationResult] = []
    with ThreadPoolExecutor(max_workers=min(len(checkable), MAX_GROUPS)) as pool:
        futures = {pool.submit(_check_one, m, g): m for m, g in checkable}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                pass  # one group failing shouldn't kill the whole verification

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_year(claims: list[Claim]) -> int | None:
    """
    Pull the most relevant fiscal year from claim text.
    Strategy: take the FIRST year found in the first claim — financial claims
    typically state the reporting year before any reference year.
    Falls back to max year across all claims if nothing in first claim.
    """
    pat = re.compile(r"\b(20\d{2})\b")
    # First: try first year that appears in any claim (text order = reporting year first)
    for c in claims:
        m = pat.search(c["claim"])
        if m:
            return int(m.group(1))
    return None


def _extract_numeric(text: str) -> float | None:
    """
    Extract the first dollar amount from a claim string.
    Handles: $383,285 million / $383.3 billion / 383285
    Returns value normalised to millions.
    """
    # e.g. $383,285 million  or  $383.3 billion  or  $6.13
    pat = re.compile(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(million|billion|thousand|trillion)?",
        re.I,
    )
    m = pat.search(text)
    if not m:
        return None
    raw = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "million").lower()
    multipliers = {"thousand": 0.001, "million": 1.0,
                   "billion": 1000.0, "trillion": 1_000_000.0}
    return raw * multipliers.get(unit, 1.0)


def _group_by_metric(claims: list[Claim]) -> dict[str, list[Claim]]:
    groups: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        label = _classify_metric(claim["claim"])
        groups[label].append(claim)
    return dict(groups)


def _classify_metric(text: str) -> str:
    for label, pattern in _METRIC_PATTERNS:
        if pattern.search(text):
            return label
    return "other"
