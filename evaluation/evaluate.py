"""
Evaluation harness for the Financial Audit Assistant.

Metrics:
  citation_accuracy  — fraction of gold pages covered by at least one cited page
  faithfulness       — fraction of memo findings traceable to a retrieved chunk

Run:
  cd finaudit
  python -m evaluation.evaluate --doc_path data/your_report.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Metric functions (pure, easy to unit-test)
# ---------------------------------------------------------------------------

def citation_accuracy(cited_pages: list[int], gold_pages: list[int]) -> float:
    """
    What fraction of gold pages appear in the cited pages?

    A score of 1.0 means every gold page was cited at least once.
    Returns 0.0 if gold_pages is empty (no ground truth to compare).
    """
    if not gold_pages:
        return 0.0
    cited_set = set(cited_pages)
    hits = sum(1 for p in gold_pages if p in cited_set)
    return hits / len(gold_pages)


def faithfulness(findings: list[str], retrieved_texts: list[str]) -> float:
    """
    What fraction of memo findings can be traced back to a retrieved chunk?

    Traceability check: any 5-gram from the finding appears in at least one chunk.
    This is a lightweight proxy for the LLM-as-judge faithfulness metric.
    """
    if not findings:
        return 0.0

    def ngrams(text: str, n: int = 5) -> set[str]:
        words = text.lower().split()
        return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}

    corpus_ngrams: set[str] = set()
    for text in retrieved_texts:
        corpus_ngrams |= ngrams(text)

    traceable = 0
    for finding in findings:
        finding_ngrams = ngrams(finding)
        if finding_ngrams and (finding_ngrams & corpus_ngrams):
            traceable += 1

    return traceable / len(findings)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_evaluation(doc_path: str, test_set_path: str = "evaluation/test_set.json") -> None:
    # Late imports so the module can be imported without a full env
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from graph.workflow import build_graph, empty_state
    from ingest.hybrid_retriever import HybridRetriever
    from ingest.pdf_parser import parse_pdf

    test_cases = json.loads(Path(test_set_path).read_text(encoding="utf-8"))

    # Index the document
    print(f"Indexing {doc_path} ...")
    retriever = HybridRetriever()
    doc_id = Path(doc_path).stem
    chunks = parse_pdf(doc_path, doc_id=doc_id)
    retriever.index_documents(chunks)
    print(f"  → {len(chunks)} chunks indexed.")

    graph = build_graph(retriever)

    accuracy_scores: list[float] = []
    faith_scores: list[float] = []
    skipped = 0

    for case in test_cases:
        # Replace placeholder with real doc_id
        case_doc_ids = [doc_id if d == "PLACEHOLDER_DOC" else d for d in case["doc_ids"]]
        gold_pages: list[int] = case.get("gold_pages", [])

        if not gold_pages:
            skipped += 1
            continue

        print(f"\n[{case['id']}] {case['question'][:80]}")
        state = empty_state(question=case["question"], doc_ids=case_doc_ids)
        result = graph.invoke(state)

        memo = result.get("memo")
        if memo is None:
            print("  ✗ No memo produced.")
            accuracy_scores.append(0.0)
            faith_scores.append(0.0)
            continue

        cited_pages = [c["source_page"] for c in memo.get("citations", [])]
        retrieved_texts = [c["text"] for c in result.get("retrieved_chunks", [])]

        acc = citation_accuracy(cited_pages, gold_pages)
        faith = faithfulness(memo.get("findings", []), retrieved_texts)

        accuracy_scores.append(acc)
        faith_scores.append(faith)
        print(f"  citation_accuracy={acc:.2f}  faithfulness={faith:.2f}")
        print(f"  cited pages: {cited_pages}  gold pages: {gold_pages}")

    print("\n" + "=" * 50)
    if accuracy_scores:
        print(f"Mean citation accuracy : {sum(accuracy_scores)/len(accuracy_scores):.3f}")
        print(f"Mean faithfulness      : {sum(faith_scores)/len(faith_scores):.3f}")
        print(f"Questions evaluated    : {len(accuracy_scores)}")
    print(f"Skipped (no gold_pages): {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the audit pipeline.")
    parser.add_argument("--doc_path", required=True, help="Path to a PDF to index and test.")
    parser.add_argument(
        "--test_set",
        default="evaluation/test_set.json",
        help="Path to test_set.json (default: evaluation/test_set.json)",
    )
    args = parser.parse_args()
    run_evaluation(doc_path=args.doc_path, test_set_path=args.test_set)
