"""
LangGraph workflow (Phase 2):

  START → retrieval → evidence_extractor
        → (conditional: no claims → memo_generator)
        → cross_verifier → review_gate → memo_generator → END

review_gate is the Phase 2 addition. It reads claims + verification_results,
routes low-confidence or flagged claims to the PostgreSQL review queue, and
passes only auto-approved claims to memo_generator.
"""

from __future__ import annotations

import uuid

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

import config
from agents.cross_verifier import verify_claims
from agents.evidence_extractor import extract_claims
from agents.memo_generator import generate_memo
from database.models import ReviewQueue
from database.session import SessionLocal, create_tables
from graph.state import AuditState, Claim, ReviewItem
from ingest.hybrid_retriever import HybridRetriever


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------

def _make_retrieval_node(retriever: HybridRetriever):
    def retrieval_node(state: AuditState) -> dict:
        chunks = retriever.retrieve(
            query=state["question"],
            doc_ids=state["doc_ids"],
            top_k=config.TOP_K_RETRIEVAL,
        )
        return {"retrieved_chunks": chunks}
    return retrieval_node


def _make_extractor_node(llm: ChatOpenAI):
    def evidence_extractor_node(state: AuditState) -> dict:
        claims = extract_claims(
            chunks=state["retrieved_chunks"],
            question=state["question"],
            llm=llm,
        )
        return {"claims": claims}
    return evidence_extractor_node


def _make_verifier_node(llm: ChatOpenAI):
    def cross_verifier_node(state: AuditState) -> dict:
        results = verify_claims(claims=state["claims"], llm=llm)
        return {"verification_results": results}
    return cross_verifier_node


def _make_review_gate_node(session_id: str):
    """
    Splits claims into auto-approved vs pending-review based on:
      - confidence < CONFIDENCE_THRESHOLD  →  "low_confidence"
      - claim appears in a 'warning' VerificationResult  →  "inconsistency_flagged"
    Inserts pending items into the review_queue DB table.
    """
    def review_gate_node(state: AuditState) -> dict:
        # Build set of claim texts that are part of a flagged inconsistency
        flagged_texts: set[str] = {
            c["claim"]
            for vr in state.get("verification_results", [])
            if vr["status"] == "warning"
            for c in vr["supporting_claims"]
        }

        auto_approved: list[Claim] = []
        pending: list[ReviewItem] = []

        with SessionLocal() as db:
            for claim in state.get("claims", []):
                low_conf    = claim["confidence"] < config.CONFIDENCE_THRESHOLD
                inconsistent = claim["claim"] in flagged_texts

                if low_conf or inconsistent:
                    if low_conf and inconsistent:
                        reason = "both"
                    elif low_conf:
                        reason = "low_confidence"
                    else:
                        reason = "inconsistency_flagged"

                    row = ReviewQueue(
                        session_id=session_id,
                        claim=claim["claim"],
                        source_doc=claim["source_doc"],
                        source_page=claim["source_page"],
                        paragraph=claim["paragraph"],
                        confidence=claim["confidence"],
                        flag_reason=reason,
                        status="pending",
                    )
                    db.add(row)
                    db.flush()   # get auto-assigned id before commit
                    pending.append(
                        ReviewItem(
                            id=row.id,
                            claim=claim["claim"],
                            source_doc=claim["source_doc"],
                            source_page=claim["source_page"],
                            paragraph=claim["paragraph"],
                            confidence=claim["confidence"],
                            flag_reason=reason,
                            status="pending",
                            reviewer_note=None,
                        )
                    )
                else:
                    auto_approved.append(claim)

            db.commit()

        return {
            "approved_claims":    auto_approved,
            "pending_review":     pending,
            "has_pending_review": len(pending) > 0,
        }
    return review_gate_node


def _make_memo_node(llm: ChatOpenAI):
    def memo_generator_node(state: AuditState) -> dict:
        # Use approved_claims if review gate ran; fall back to all claims otherwise
        claims = state.get("approved_claims") or state.get("claims", [])
        memo = generate_memo(
            claims=claims,
            verification_results=state.get("verification_results", []),
            question=state["question"],
            llm=llm,
            n_pending=len(state.get("pending_review", [])),
        )
        return {"memo": memo}
    return memo_generator_node


# ---------------------------------------------------------------------------
# Conditional edge
# ---------------------------------------------------------------------------

def _route_after_extraction(state: AuditState) -> str:
    if state.get("claims"):
        return "cross_verifier"
    return "memo_generator"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(retriever: HybridRetriever) -> "CompiledStateGraph":
    create_tables()   # idempotent — safe to call on every startup

    llm = ChatOpenAI(
        model=config.LLM_MODEL,
        api_key=config.GROQ_API_KEY,
        base_url=config.GROQ_BASE_URL,
        temperature=0,
    )

    session_id = str(uuid.uuid4())[:16]

    graph = StateGraph(AuditState)

    graph.add_node("retrieval",          _make_retrieval_node(retriever))
    graph.add_node("evidence_extractor", _make_extractor_node(llm))
    graph.add_node("cross_verifier",     _make_verifier_node(llm))
    graph.add_node("review_gate",        _make_review_gate_node(session_id))
    graph.add_node("memo_generator",     _make_memo_node(llm))

    graph.add_edge(START, "retrieval")
    graph.add_edge("retrieval", "evidence_extractor")
    graph.add_conditional_edges(
        "evidence_extractor",
        _route_after_extraction,
        {"cross_verifier": "cross_verifier", "memo_generator": "memo_generator"},
    )
    graph.add_edge("cross_verifier", "review_gate")
    graph.add_edge("review_gate",    "memo_generator")
    graph.add_edge("memo_generator", END)

    return graph.compile()


def empty_state(question: str, doc_ids: list[str]) -> AuditState:
    return AuditState(
        question=question,
        doc_ids=doc_ids,
        retrieved_chunks=[],
        claims=[],
        verification_results=[],
        approved_claims=[],
        pending_review=[],
        has_pending_review=False,
        memo=None,
    )
