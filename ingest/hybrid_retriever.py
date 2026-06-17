"""
HybridRetriever: BM25 (rank_bm25) + dense (ChromaDB + sentence-transformers).
Scores are fused with Reciprocal Rank Fusion (RRF, k=60).

Usage:
    retriever = HybridRetriever()
    retriever.index_documents(chunks)
    results = retriever.retrieve("total revenue", doc_ids=["aapl_10k_2023"], top_k=10)
"""

from __future__ import annotations

import uuid
from collections import defaultdict

import torch
import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

import config
from graph.state import Chunk


class HybridRetriever:
    def __init__(self) -> None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[HybridRetriever] embedding device: {device}")
        self._embedder = SentenceTransformer(config.EMBED_MODEL, device=device)
        self._chroma = chromadb.PersistentClient(path=config.CHROMA_PATH)
        self._collection = self._chroma.get_or_create_collection(
            name="finaudit_chunks",
            metadata={"hnsw:space": "cosine"},
        )

        # BM25 state — rebuilt each time index_documents is called
        self._bm25: BM25Okapi | None = None
        self._bm25_chunks: list[Chunk] = []

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def is_doc_indexed(self, doc_id: str) -> bool:
        """True if ChromaDB already has chunks for this doc_id."""
        result = self._collection.get(
            where={"doc_id": doc_id}, limit=1, include=[]
        )
        return len(result["ids"]) > 0

    def rebuild_bm25_from_chroma(self) -> int:
        """Rebuild in-memory BM25 from existing ChromaDB data (no embedding). Returns chunk count."""
        existing = self._collection.get(include=["documents", "metadatas"])
        if not existing["documents"]:
            return 0
        self._bm25_chunks = [
            Chunk(
                text=t,
                doc_id=m["doc_id"],
                page_num=m["page_num"],
                paragraph_idx=m["paragraph_idx"],
                section=m["section"],
            )
            for t, m in zip(existing["documents"], existing["metadatas"])
        ]
        self._bm25 = BM25Okapi([c["text"].lower().split() for c in self._bm25_chunks])
        return len(self._bm25_chunks)

    def index_documents(self, chunks: list[Chunk]) -> None:
        """Add chunks to ChromaDB and rebuild the in-memory BM25 index."""
        if not chunks:
            return

        # --- ChromaDB ---
        texts = [c["text"] for c in chunks]
        embeddings = self._embedder.encode(
            texts, show_progress_bar=False, batch_size=64
        ).tolist()
        metadatas = [
            {
                "doc_id": c["doc_id"],
                "page_num": c["page_num"],
                "paragraph_idx": c["paragraph_idx"],
                "section": c["section"],
            }
            for c in chunks
        ]
        # Deterministic IDs so upsert deduplicates instead of appending
        ids = [f"{c['doc_id']}::{c['page_num']}::{c['paragraph_idx']}" for c in chunks]

        self._collection.upsert(
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )

        self.rebuild_bm25_from_chroma()

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        doc_ids: list[str] | None = None,
        top_k: int = config.TOP_K_RETRIEVAL,
    ) -> list[Chunk]:
        """
        Return top_k chunks fused via RRF.

        Args:
            query:   Natural-language question.
            doc_ids: If provided, restrict results to these document IDs.
            top_k:   Number of chunks to return.
        """
        if self._bm25 is None or not self._bm25_chunks:
            return []

        candidate_pool = len(self._bm25_chunks)
        fetch_n = min(candidate_pool, max(top_k * 3, 30))

        # --- BM25 scores ---
        bm25_scores = self._bm25.get_scores(query.lower().split())
        bm25_ranked = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)

        # Filter by doc_ids if given
        if doc_ids:
            doc_id_set = set(doc_ids)
            bm25_ranked = [i for i in bm25_ranked if self._bm25_chunks[i]["doc_id"] in doc_id_set]

        bm25_ranked = bm25_ranked[:fetch_n]

        # --- Dense scores via ChromaDB ---
        query_embedding = self._embedder.encode([query], show_progress_bar=False).tolist()
        where_filter = {"doc_id": {"$in": list(doc_ids)}} if doc_ids else None

        dense_results = self._collection.query(
            query_embeddings=query_embedding,
            n_results=min(fetch_n, self._collection.count() or 1),
            where=where_filter,
            include=["documents", "metadatas"],
        )
        dense_chunks: list[Chunk] = []
        if dense_results["documents"] and dense_results["documents"][0]:
            for text, meta in zip(
                dense_results["documents"][0], dense_results["metadatas"][0]
            ):
                dense_chunks.append(
                    Chunk(
                        text=text,
                        doc_id=meta["doc_id"],
                        page_num=meta["page_num"],
                        paragraph_idx=meta["paragraph_idx"],
                        section=meta["section"],
                    )
                )

        # --- RRF fusion ---
        rrf_scores: dict[str, float] = defaultdict(float)

        def chunk_key(c: Chunk) -> str:
            return f"{c['doc_id']}::{c['page_num']}::{c['paragraph_idx']}"

        # BM25 contribution
        for rank, idx in enumerate(bm25_ranked):
            key = chunk_key(self._bm25_chunks[idx])
            rrf_scores[key] += 1.0 / (config.RRF_K + rank + 1)

        # Dense contribution
        for rank, chunk in enumerate(dense_chunks):
            key = chunk_key(chunk)
            rrf_scores[key] += 1.0 / (config.RRF_K + rank + 1)

        # Build a lookup so we can return Chunk objects
        chunk_lookup: dict[str, Chunk] = {
            chunk_key(c): c for c in self._bm25_chunks
        }
        for c in dense_chunks:
            key = chunk_key(c)
            if key not in chunk_lookup:
                chunk_lookup[key] = c

        ranked_keys = sorted(rrf_scores, key=rrf_scores.__getitem__, reverse=True)
        return [chunk_lookup[k] for k in ranked_keys[:top_k] if k in chunk_lookup]
