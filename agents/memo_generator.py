"""
Audit Memo Generator Agent

Synthesises extracted claims and cross-verification results into a structured
audit memo with four sections: executive summary, findings, flagged
inconsistencies, and citations.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from graph.state import AuditMemo, Claim, VerificationResult


# ---------------------------------------------------------------------------
# Pydantic response model
# ---------------------------------------------------------------------------

class MemoModel(BaseModel):
    executive_summary: str = Field(
        description="2-3 sentence overview of what the document says about the question."
    )
    findings: list[str] = Field(
        description="Bullet-point findings drawn directly from the extracted claims."
    )
    flagged_inconsistencies: list[str] = Field(
        description=(
            "Each warning from the cross-verification step, stated as a plain sentence. "
            "Empty list if everything is consistent."
        )
    )


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior financial auditor writing an internal audit memo. \
Your memo must be grounded only in the provided claims and verification results — \
do not add facts from external knowledge. Use precise language and cite figures exactly as given."""


def generate_memo(
    claims: list[Claim],
    verification_results: list[VerificationResult],
    question: str,
    llm: ChatOpenAI,
    n_pending: int = 0,
) -> AuditMemo:
    """
    Generate a structured audit memo from claims and verification results.

    Args:
        claims:               All extracted claims.
        verification_results: Cross-verification outcomes.
        question:             The original audit question.
        llm:                  A ChatOpenAI instance.

    Returns:
        AuditMemo TypedDict with all four fields populated.
    """
    structured_llm = llm.with_structured_output(MemoModel, method="function_calling")

    claims_text = "\n".join(
        f"- [Doc: {c['source_doc']} | Page {c['source_page']}] {c['claim']} "
        f"(confidence: {c['confidence']:.2f})"
        for c in claims
    ) or "No claims were extracted."

    verif_text = "\n".join(
        f"- Metric '{r['metric']}': {r['status'].upper()} — {r['reason']}"
        + (f" ({r['difference']})" if r["difference"] else "")
        for r in verification_results
    ) or "No cross-verification was performed."

    pending_note = (
        f"\nNOTE: {n_pending} claim(s) were routed to human review (low confidence or "
        f"inconsistency flagged) and are NOT included in the claims above. "
        f"This memo reflects only auto-approved claims."
        if n_pending > 0 else ""
    )

    user_msg = (
        f"Audit Question: {question}\n\n"
        f"Extracted Claims:\n{claims_text}\n\n"
        f"Cross-Verification Results:\n{verif_text}"
        f"{pending_note}\n\n"
        "Write an audit memo covering: executive summary, key findings, and any flagged inconsistencies."
    )

    response = structured_llm.invoke(
        [{"role": "system", "content": _SYSTEM_PROMPT},
         {"role": "user", "content": user_msg}]
    )

    if isinstance(response, dict):
        exec_summary   = response.get("executive_summary", "")
        findings       = response.get("findings", [])
        flagged        = response.get("flagged_inconsistencies", [])
    else:
        exec_summary   = response.executive_summary
        findings       = response.findings
        flagged        = response.flagged_inconsistencies

    citations = sorted(claims, key=lambda c: c["confidence"], reverse=True)

    return AuditMemo(
        executive_summary=exec_summary,
        findings=findings,
        flagged_inconsistencies=flagged,
        citations=citations,
    )
