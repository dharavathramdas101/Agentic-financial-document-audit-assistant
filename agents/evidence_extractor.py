"""
Evidence Extractor Agent

Given retrieved chunks and the user's question, calls an LLM with structured
output to extract specific factual claims with page-level citations.

Each chunk batch (≤5 chunks) gets one LLM call to stay within context limits.
Results from all batches are flattened into a single list[Claim].
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from graph.state import Chunk, Claim


# ---------------------------------------------------------------------------
# Pydantic response models (used by .with_structured_output)
# ---------------------------------------------------------------------------

class ClaimModel(BaseModel):
    claim: str = Field(description="One complete sentence stating a specific fact with its numeric value. Must be a full sentence, not a bare number.")
    source_page: int = Field(description="Page number where this claim appears.")
    paragraph: int = Field(description="Paragraph index on that page (0-based).")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence that this claim is accurate and relevant.")


class ClaimsResponse(BaseModel):
    claims: list[ClaimModel] = Field(
        description="Distinct factual claims relevant to the question. Maximum 8 claims total.",
        max_length=8,
    )


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial document analyst. Given excerpts from a financial report and a question, \
extract factual claims relevant to the question. Rules:
1. Each claim must be a COMPLETE SENTENCE (e.g. "Apple's net revenue for FY2023 was $383,285 million.").
2. Never output bare numbers or single words as claims.
3. Extract at most 8 distinct claims total — stop after 8.
4. Only extract claims directly stated in the text."""

_BATCH_SIZE = 3  # smaller batches = less context = 8b model stays on track


def extract_claims(
    chunks: list[Chunk],
    question: str,
    llm: ChatOpenAI,
) -> list[Claim]:
    """
    Extract structured claims from retrieved chunks.

    Args:
        chunks:   Chunks returned by the retriever.
        question: The original audit question.
        llm:      A ChatOpenAI instance (will be wrapped with structured output).

    Returns:
        Flat list of Claim dicts from all batches.
    """
    structured_llm = llm.with_structured_output(ClaimsResponse, method="function_calling")
    all_claims: list[Claim] = []

    for batch_start in range(0, len(chunks), _BATCH_SIZE):
        batch = chunks[batch_start : batch_start + _BATCH_SIZE]
        excerpts = _format_excerpts(batch)

        user_msg = (
            f"Question: {question}\n\n"
            f"Document excerpts:\n{excerpts}\n\n"
            "Extract up to 8 factual claims relevant to the question. "
            "Each claim must be a complete sentence containing the numeric value and its context."
        )

        response = structured_llm.invoke(
            [{"role": "system", "content": _SYSTEM_PROMPT},
             {"role": "user", "content": user_msg}]
        )

        seen: set[str] = {c["claim"] for c in all_claims}
        if isinstance(response, dict):
            raw_claims = response.get("claims") or []
        elif hasattr(response, "claims"):
            raw_claims = response.claims or []
        else:
            raw_claims = []
        for c in raw_claims:
            # Normalise: Pydantic object or dict
            if isinstance(c, dict):
                text  = c.get("claim", "")
                page  = c.get("source_page", 0)
                para  = c.get("paragraph", 0)
                conf  = c.get("confidence", 0.5)
            else:
                text  = c.claim
                page  = c.source_page
                para  = c.paragraph
                conf  = c.confidence
            # Drop bare numbers / single tokens and duplicates
            if not text or len(text.split()) < 4:
                continue
            if text in seen:
                continue
            seen.add(text)
            source_doc = _find_source_doc(batch, page)
            all_claims.append(
                Claim(
                    claim=text,
                    source_doc=source_doc,
                    source_page=page,
                    paragraph=para,
                    confidence=float(conf),
                )
            )
        if len(all_claims) >= 8:
            break  # hit global cap — no more batches needed

    return all_claims


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_excerpts(chunks: list[Chunk]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        parts.append(
            f"[Excerpt {i} | Doc: {chunk['doc_id']} | Page: {chunk['page_num']} "
            f"| Para: {chunk['paragraph_idx']} | Section: {chunk['section']}]\n"
            f"{chunk['text']}"
        )
    return "\n\n---\n\n".join(parts)


def _find_source_doc(batch: list[Chunk], page_num: int) -> str:
    for chunk in batch:
        if chunk["page_num"] == page_num:
            return chunk["doc_id"]
    return batch[0]["doc_id"] if batch else "unknown"
