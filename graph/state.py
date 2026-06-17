from typing import TypedDict, Literal


class Chunk(TypedDict):
    text: str
    doc_id: str          # filename stem, e.g. "aapl_10k_2023"
    page_num: int
    paragraph_idx: int
    section: str         # nearest heading above this block, or "unknown"


class Claim(TypedDict):
    claim: str
    source_doc: str
    source_page: int
    paragraph: int
    confidence: float    # 0.0–1.0, as assessed by the LLM


class VerificationResult(TypedDict):
    metric: str                               # e.g. "revenue"
    status: Literal["consistent", "warning"]
    reason: str
    difference: str | None                    # e.g. "₹120 Cr vs ₹118 Cr"
    supporting_claims: list[Claim]


class AuditMemo(TypedDict):
    executive_summary: str
    findings: list[str]
    flagged_inconsistencies: list[str]
    citations: list[Claim]


# ---------------------------------------------------------------------------
# Phase 2 additions — human review queue
# ---------------------------------------------------------------------------

class ReviewItem(TypedDict):
    """A claim that failed the confidence gate or was flagged by cross-verifier."""
    id: int                  # DB primary key assigned after INSERT
    claim: str
    source_doc: str
    source_page: int
    paragraph: int
    confidence: float
    flag_reason: str         # "low_confidence" | "inconsistency_flagged" | "both"
    status: str              # "pending" | "approved" | "rejected"
    reviewer_note: str | None


class AuditState(TypedDict):
    question: str
    doc_ids: list[str]
    retrieved_chunks: list[Chunk]              # populated by retrieval node
    claims: list[Claim]                        # populated by evidence extractor node
    verification_results: list[VerificationResult]  # populated by cross verifier node
    # Phase 2 — populated by review_gate node
    approved_claims: list[Claim]               # high-confidence, consistent claims
    pending_review: list[ReviewItem]           # routed to DB for human review
    has_pending_review: bool
    memo: AuditMemo | None                     # populated by memo generator node
