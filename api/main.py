"""
FastAPI application — two endpoints:

  POST /index   Index one or more PDF files.
  POST /audit   Run the full audit pipeline on a question + doc set.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database.models import ReviewQueue
from database.session import SessionLocal, create_tables
from graph.state import AuditMemo
from graph.workflow import build_graph, empty_state
from ingest.hybrid_retriever import HybridRetriever
from ingest.pdf_parser import parse_pdf
from ingest.table_extractor import extract_tables_from_pdf, get_all_records, store_financial_records


# ---------------------------------------------------------------------------
# App lifespan: build shared objects once at startup
# ---------------------------------------------------------------------------

_retriever: HybridRetriever | None = None
_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _retriever, _graph
    create_tables()
    _retriever = HybridRetriever()
    # Rebuild BM25 from persisted ChromaDB data — survives server restarts
    n = _retriever.rebuild_bm25_from_chroma()
    if n:
        print(f"[startup] Reloaded {n} chunks from ChromaDB into BM25.")
    _graph = build_graph(_retriever)
    yield
    # cleanup (nothing needed for in-process ChromaDB)


app = FastAPI(
    title="Financial Document Audit Assistant",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class IndexRequest(BaseModel):
    doc_paths: list[str]


class IndexResponse(BaseModel):
    indexed_doc_ids: list[str]
    total_chunks: int
    total_table_records: int


class AuditRequest(BaseModel):
    question: str
    doc_ids: list[str]


class AuditResponse(BaseModel):
    memo: AuditMemo
    processing_time_s: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/index", response_model=IndexResponse)
def index_documents(req: IndexRequest) -> IndexResponse:
    """
    Parse PDFs and add their chunks to the retriever index.

    Accepts absolute or relative paths to PDF files. Returns the doc_ids
    assigned (= filename stem) and total chunks indexed.
    """
    if _retriever is None:
        raise HTTPException(status_code=503, detail="Retriever not initialised.")

    total_chunks = 0
    doc_ids = []
    total_table_records = 0

    for path_str in req.doc_paths:
        path = Path(path_str)
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"File not found: {path_str}")
        if path.suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail=f"Not a PDF: {path_str}")

        doc_id = path.stem
        doc_ids.append(doc_id)

        if _retriever.is_doc_indexed(doc_id):
            # Already embedded in ChromaDB — skip encode (saves ~45s), just count
            n = len(_retriever._collection.get(where={"doc_id": doc_id}, include=[])["ids"])
            total_chunks += n
        else:
            chunks = parse_pdf(str(path))
            _retriever.index_documents(chunks)
            total_chunks += len(chunks)

        # Skip pdfplumber if table records already exist for this doc
        from database.models import FinancialRecord
        with SessionLocal() as db:
            existing_tables = db.query(FinancialRecord).filter_by(doc_id=doc_id).count()
        if existing_tables == 0:
            table_records = extract_tables_from_pdf(str(path), doc_id=doc_id)
            total_table_records += store_financial_records(table_records, doc_id=doc_id)
        else:
            total_table_records += existing_tables

    return IndexResponse(
        indexed_doc_ids=doc_ids,
        total_chunks=total_chunks,
        total_table_records=total_table_records,
    )


@app.post("/audit", response_model=AuditResponse)
def audit(req: AuditRequest) -> AuditResponse:
    """
    Run the LangGraph audit pipeline and return a structured memo.

    The doc_ids must match stems of previously indexed PDFs.
    """
    if _graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialised.")

    t0 = time.perf_counter()

    initial_state = empty_state(question=req.question, doc_ids=req.doc_ids)
    final_state = _graph.invoke(initial_state)

    if final_state.get("memo") is None:
        raise HTTPException(status_code=500, detail="Pipeline produced no memo.")

    return AuditResponse(
        memo=final_state["memo"],
        processing_time_s=round(time.perf_counter() - t0, 2),
    )


@app.post("/audit/stream")
def audit_stream(req: AuditRequest) -> StreamingResponse:
    """
    Server-Sent Events endpoint — yields one JSON event per LangGraph node.

    Events:
      data: {"node":"retrieval",          "chunks":N}
      data: {"node":"evidence_extractor", "claims":N}
      data: {"node":"cross_verifier",     "verifications":N}
      data: {"node":"memo_generator",     "memo":{...}}
    """
    if _graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialised.")

    def generate():
        state = empty_state(question=req.question, doc_ids=req.doc_ids)
        try:
            for event in _graph.stream(state, stream_mode="updates"):
                node_name: str = next(iter(event))
                node_data: dict = event[node_name]

                if node_name == "retrieval":
                    msg = {"node": "retrieval",
                           "chunks": len(node_data.get("retrieved_chunks", []))}
                elif node_name == "evidence_extractor":
                    msg = {"node": "evidence_extractor",
                           "claims": len(node_data.get("claims", []))}
                elif node_name == "cross_verifier":
                    results = node_data.get("verification_results", [])
                    n_structured = sum(
                        1 for r in results
                        if isinstance(r, dict) and "[STRUCTURED]" in r.get("reason", "")
                    )
                    msg = {"node": "cross_verifier",
                           "verifications": len(results),
                           "structured": n_structured,
                           "llm_fallback": len(results) - n_structured}
                elif node_name == "review_gate":
                    msg = {"node": "review_gate",
                           "approved": len(node_data.get("approved_claims", [])),
                           "pending":  len(node_data.get("pending_review", []))}
                elif node_name == "memo_generator":
                    msg = {"node": "memo_generator",
                           "memo": node_data.get("memo")}
                else:
                    continue

                yield f"data: {json.dumps(msg)}\n\n"
        except Exception as exc:
            msg = str(exc)
            # Surface rate-limit errors with a human-readable hint
            if "429" in msg or "rate_limit_exceeded" in msg:
                import re
                wait = re.search(r"try again in (.+?)\.", msg)
                hint = f"Groq daily token limit reached. Try again in {wait.group(1)}." if wait \
                       else "Groq daily token limit reached. Try again tomorrow or switch to llama-3.1-8b-instant in .env."
                yield f"data: {json.dumps({'node': 'rate_limit', 'message': hint})}\n\n"
            else:
                yield f"data: {json.dumps({'node': 'error', 'message': msg})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/tables/{doc_id}")
def get_tables(doc_id: str, table_type: str | None = None, year: int | None = None) -> list[dict]:
    """
    Inspect extracted financial table records for a document.

    Optional filters: ?table_type=income_statement  ?year=2023
    """
    from database.models import FinancialRecord
    with SessionLocal() as db:
        q = db.query(FinancialRecord).filter_by(doc_id=doc_id)
        if table_type:
            q = q.filter_by(table_type=table_type)
        if year:
            q = q.filter_by(year=year)
        rows = q.order_by(FinancialRecord.table_type, FinancialRecord.year.desc()).all()
        return [r.to_dict() for r in rows]


# ---------------------------------------------------------------------------
# Human Review Queue endpoints
# ---------------------------------------------------------------------------

class ReviewActionRequest(BaseModel):
    reviewer_note: str = ""


@app.get("/review/stats")
def review_stats() -> dict:
    """Count of items per status."""
    with SessionLocal() as db:
        total    = db.query(ReviewQueue).count()
        pending  = db.query(ReviewQueue).filter_by(status="pending").count()
        approved = db.query(ReviewQueue).filter_by(status="approved").count()
        rejected = db.query(ReviewQueue).filter_by(status="rejected").count()
    return {"total": total, "pending": pending, "approved": approved, "rejected": rejected}


@app.get("/review/pending")
def list_pending() -> list[dict]:
    """Return all claims currently in 'pending' status."""
    with SessionLocal() as db:
        rows = db.query(ReviewQueue).filter_by(status="pending").order_by(ReviewQueue.id).all()
        return [r.to_dict() for r in rows]


@app.get("/review/{item_id}")
def get_review_item(item_id: int) -> dict:
    with SessionLocal() as db:
        row = db.get(ReviewQueue, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Review item {item_id} not found.")
        return row.to_dict()


@app.post("/review/{item_id}/approve")
def approve_item(item_id: int, req: ReviewActionRequest) -> dict:
    """Mark a pending claim as approved."""
    with SessionLocal() as db:
        row = db.get(ReviewQueue, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Review item {item_id} not found.")
        if row.status != "pending":
            raise HTTPException(status_code=400, detail=f"Item {item_id} is already '{row.status}'.")
        row.status = "approved"
        row.reviewer_note = req.reviewer_note or None
        db.commit()
        return {"id": item_id, "status": "approved", "message": "Claim approved."}


@app.post("/review/{item_id}/reject")
def reject_item(item_id: int, req: ReviewActionRequest) -> dict:
    """Mark a pending claim as rejected."""
    with SessionLocal() as db:
        row = db.get(ReviewQueue, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Review item {item_id} not found.")
        if row.status != "pending":
            raise HTTPException(status_code=400, detail=f"Item {item_id} is already '{row.status}'.")
        row.status = "rejected"
        row.reviewer_note = req.reviewer_note or None
        db.commit()
        return {"id": item_id, "status": "rejected", "message": "Claim rejected."}
