"""
Ragas-style generation metrics — hand-implemented with explicit LLM calls.

Why not use the ragas library?
  ragas 0.4.x is incompatible with langchain>=1.0 (it imports a removed
  VertexAI module). ragas 0.1.x requires langchain<0.3, which downgrades our
  entire stack. Rather than fight dependency hell, we implement the same three
  metrics ourselves so every computation step is fully visible and explainable.

Metrics
-------
Faithfulness
    "Are all claims in the answer supported by the retrieved context?"
    Method (mirrors Ragas v1):
      1. Ask LLM to decompose the answer into atomic statements.
      2. For each statement, ask LLM: "Is this statement supported by the
         provided context passages? Answer YES or NO."
      3. faithfulness = YES_count / total_statements

Answer Relevancy
    "Does the answer address what was asked?"
    Method (mirrors Ragas v1):
      1. Ask LLM to generate N synthetic questions that the answer appears
         to answer.
      2. Embed the original question and each synthetic question.
      3. relevancy = mean cosine_similarity(original_q_embedding,
                                            synthetic_q_embedding)

Context Precision
    "Are the retrieved passages actually relevant to the question?"
    Method (mirrors Ragas v1):
      1. For each retrieved chunk (in rank order), ask LLM: "Is this passage
         useful for answering the question given the gold answer? YES or NO."
      2. precision@k = (useful chunks in top-k) / k, averaged with
         rank-aware weighting:
         context_precision = mean_k( precision@k * relevant_at_k )
         where relevant_at_k = 1 if chunk k is useful, else 0.

Run:
  cd finaudit
  python -m evaluation.ragas_style_eval --doc_path data/aapl-20230930.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import openai

import numpy as np
from langchain_openai import ChatOpenAI
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from evaluation.retrieval_metrics import compute_retrieval_metrics
from evaluation.evaluate import citation_accuracy
from graph.workflow import build_graph, empty_state
from ingest.hybrid_retriever import HybridRetriever
from ingest.pdf_parser import parse_pdf


# ---------------------------------------------------------------------------
# LLM helper — YES/NO judge
# ---------------------------------------------------------------------------

def _yes_no(llm: ChatOpenAI, prompt: str) -> bool:
    for attempt in range(5):
        try:
            resp = llm.invoke([{"role": "user", "content": prompt}])
            return resp.content.strip().upper().startswith("Y")
        except openai.RateLimitError as e:
            wait = 60 * (attempt + 1)
            print(f"\n  [rate limit] waiting {wait}s before retry {attempt+1}/5...")
            time.sleep(wait)
    return False


def _llm_call(llm: ChatOpenAI, messages: list) -> str:
    for attempt in range(5):
        try:
            return llm.invoke(messages).content
        except openai.RateLimitError:
            wait = 60 * (attempt + 1)
            print(f"\n  [rate limit] waiting {wait}s before retry {attempt+1}/5...")
            time.sleep(wait)
    return ""


# ---------------------------------------------------------------------------
# Faithfulness
# ---------------------------------------------------------------------------

def _decompose_answer(llm: ChatOpenAI, answer: str) -> list[str]:
    prompt = (
        "Decompose the following answer into a numbered list of atomic factual "
        "statements. Each statement must be a single sentence. "
        "Return ONLY the numbered list, nothing else.\n\n"
        f"Answer:\n{answer}"
    )
    raw = _llm_call(llm, [{"role": "user", "content": prompt}])
    statements = [
        re.sub(r"^\d+[\.\)]\s*", "", line).strip()
        for line in raw.strip().splitlines()
        if re.match(r"^\d+", line.strip())
    ]
    return [s for s in statements if s]


def faithfulness_score(
    llm: ChatOpenAI,
    answer: str,
    contexts: list[str],
) -> float:
    """
    Faithfulness = supported_statements / total_statements.
    Returns 1.0 if answer is empty (nothing to hallucinate).
    """
    statements = _decompose_answer(llm, answer)
    if not statements:
        return 1.0

    context_block = "\n\n---\n\n".join(contexts)
    supported = 0
    for stmt in statements:
        prompt = (
            f"Context passages:\n{context_block}\n\n"
            f"Statement: {stmt}\n\n"
            "Is this statement directly supported by the context passages above? "
            "Answer YES or NO only."
        )
        if _yes_no(llm, prompt):
            supported += 1

    return supported / len(statements)


# ---------------------------------------------------------------------------
# Answer Relevancy
# ---------------------------------------------------------------------------

def answer_relevancy_score(
    llm: ChatOpenAI,
    embedder: SentenceTransformer,
    question: str,
    answer: str,
    n_synthetic: int = 3,
) -> float:
    """
    Answer Relevancy = mean cosine similarity between the original question
    embedding and N synthetic questions generated from the answer.
    Returns 0.0 if answer is empty.
    """
    if not answer.strip():
        return 0.0

    prompt = (
        f"Given the following answer, generate {n_synthetic} questions that "
        "this answer plausibly responds to. Return ONLY the questions, one per line.\n\n"
        f"Answer:\n{answer}"
    )
    raw = _llm_call(llm, [{"role": "user", "content": prompt}])
    synthetic_qs = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()][:n_synthetic]
    if not synthetic_qs:
        return 0.0

    all_texts = [question] + synthetic_qs
    embeddings = embedder.encode(all_texts, normalize_embeddings=True)
    q_emb = embeddings[0]
    sims = [float(np.dot(q_emb, embeddings[i])) for i in range(1, len(embeddings))]
    return float(np.mean(sims))


# ---------------------------------------------------------------------------
# Context Precision
# ---------------------------------------------------------------------------

def context_precision_score(
    llm: ChatOpenAI,
    question: str,
    gold_answer: str,
    contexts: list[str],
) -> float:
    """
    Context Precision with rank-aware averaging (AP@K style).
    Returns 0.0 if no contexts.
    """
    if not contexts:
        return 0.0

    relevance: list[bool] = []
    for ctx in contexts:
        prompt = (
            f"Question: {question}\n"
            f"Gold answer: {gold_answer}\n"
            f"Passage: {ctx}\n\n"
            "Is this passage useful for answering the question given the gold answer? "
            "Answer YES or NO only."
        )
        relevance.append(_yes_no(llm, prompt))

    # Average Precision@K
    hits, precision_sum = 0, 0.0
    for k, rel in enumerate(relevance, start=1):
        if rel:
            hits += 1
            precision_sum += hits / k
    return precision_sum / hits if hits else 0.0


# ---------------------------------------------------------------------------
# Answer builder
# ---------------------------------------------------------------------------

def _build_answer(memo) -> str:
    if memo is None:
        return ""
    parts = [memo.get("executive_summary", "")]
    parts += memo.get("findings", [])
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_evaluation(doc_path: str, test_set_path: str) -> dict:
    test_cases = json.loads(Path(test_set_path).read_text(encoding="utf-8"))

    out_dir = Path("evaluation/results")
    out_dir.mkdir(exist_ok=True)
    doc_id = Path(doc_path).stem
    checkpoint_path = out_dir / f"checkpoint_{doc_id}.json"

    # Load existing checkpoint (resume after rate-limit interruption)
    checkpoint: dict = {}
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        done_ids = set(checkpoint.keys())
        print(f"Resuming — {len(done_ids)} questions already done: {sorted(done_ids)}")
    else:
        done_ids = set()

    print(f"Indexing {doc_path} ...")
    retriever = HybridRetriever()
    chunks = parse_pdf(doc_path, doc_id=doc_id)
    retriever.index_documents(chunks)
    print(f"  {len(chunks)} chunks indexed.")

    graph    = build_graph(retriever)
    llm      = ChatOpenAI(model=config.LLM_MODEL, api_key=config.GROQ_API_KEY,
                          base_url=config.GROQ_BASE_URL, temperature=0)
    embedder = SentenceTransformer(config.EMBED_MODEL)

    skipped = 0

    for case in test_cases:
        if not case.get("gold_pages") or not case.get("gold_answer", "").strip():
            skipped += 1
            continue

        qid = case["id"]
        if qid in done_ids:
            print(f"[{qid}] already done — skip")
            continue

        q           = case["question"]
        doc_ids     = [doc_id if d == "PLACEHOLDER_DOC" else d for d in case["doc_ids"]]
        gold_pages  = case["gold_pages"]
        gold_answer = case["gold_answer"]

        print(f"\n[{qid}] {q[:70]}")

        state  = empty_state(question=q, doc_ids=doc_ids)
        result = graph.invoke(state)
        memo   = result.get("memo")
        answer = _build_answer(memo)
        ctxs   = [c["text"] for c in result.get("retrieved_chunks", [])]

        # Retrieval metrics (no LLM)
        top_pages = [c["page_num"] for c in result.get("retrieved_chunks", [])]
        cited     = [c["source_page"] for c in (memo or {}).get("citations", [])]

        # Generation metrics (LLM-as-judge, each call has retry)
        f = faithfulness_score(llm, answer, ctxs)
        r = answer_relevancy_score(llm, embedder, q, answer)
        p = context_precision_score(llm, q, gold_answer, ctxs)

        print(f"  faithfulness={f:.3f}  relevancy={r:.3f}  precision={p:.3f}")

        # Save to checkpoint immediately
        checkpoint[qid] = {
            "faithfulness":      f,
            "answer_relevancy":  r,
            "context_precision": p,
            "top_pages":         top_pages,
            "gold_pages":        gold_pages,
            "cited_pages":       cited,
        }
        checkpoint_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")

    # Aggregate from checkpoint (covers both this run + prior runs)
    faith_scores, rel_scores, prec_scores, cit_acc_scores = [], [], [], []
    retrieval_results: list[dict] = []

    for qid, row in checkpoint.items():
        faith_scores.append(row["faithfulness"])
        rel_scores.append(row["answer_relevancy"])
        prec_scores.append(row["context_precision"])
        # Rebuild chunk-like dicts for retrieval metrics
        fake_chunks = [{"page_num": p, "text": "", "doc_id": doc_id,
                        "paragraph_idx": 0, "section": ""}
                       for p in row["top_pages"]]
        retrieval_results.append({"retrieved_chunks": fake_chunks,
                                  "gold_pages": row["gold_pages"]})
        cit_acc_scores.append(citation_accuracy(row["cited_pages"], row["gold_pages"]))

    retrieval = compute_retrieval_metrics(retrieval_results)

    def _mean(lst): return round(sum(lst) / len(lst), 4) if lst else 0.0

    report = {
        "run_date":         str(date.today()),
        "doc":              doc_id,
        "n_evaluated":      len(faith_scores),
        "n_total":          len(test_cases),
        "n_skipped":        skipped,
        "generation": {
            "faithfulness":      _mean(faith_scores),
            "answer_relevancy":  _mean(rel_scores),
            "context_precision": _mean(prec_scores),
        },
        "retrieval": retrieval,
        "citation_accuracy": _mean(cit_acc_scores),
    }

    # Save JSON
    out_dir = Path("evaluation/results")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"metrics_{date.today().strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nResults saved → {out_path}")
    if len(faith_scores) < len([c for c in test_cases if c.get("gold_pages")]):
        remaining = len([c for c in test_cases if c.get("gold_pages")]) - len(faith_scores)
        print(f"  ({remaining} questions remaining — re-run tomorrow to continue)")

    # Print markdown table
    print("\n" + "=" * 60)
    print("| Metric                  | Score  |")
    print("|-------------------------|--------|")
    print(f"| Faithfulness            | {report['generation']['faithfulness']:.3f}  |")
    print(f"| Answer Relevancy        | {report['generation']['answer_relevancy']:.3f}  |")
    print(f"| Context Precision       | {report['generation']['context_precision']:.3f}  |")
    print(f"| Recall@5                | {report['retrieval'].get('recall_at_5', 0):.3f}  |")
    print(f"| Recall@10               | {report['retrieval'].get('recall_at_10', 0):.3f}  |")
    print(f"| MRR                     | {report['retrieval']['mrr']:.3f}  |")
    print(f"| Citation Accuracy       | {report['citation_accuracy']:.3f}  |")
    print(f"\nEvaluated {report['n_evaluated']} questions, skipped {report['n_skipped']}.")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc_path",  required=True)
    parser.add_argument("--test_set",  default="evaluation/test_set.json")
    args = parser.parse_args()
    run_evaluation(doc_path=args.doc_path, test_set_path=args.test_set)
