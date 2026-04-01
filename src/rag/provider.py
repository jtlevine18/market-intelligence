"""
Hybrid FAISS + BM25 RAG provider for Tamil Nadu agricultural marketing knowledge.

Uses sentence-transformers (all-MiniLM-L6-v2) for dense semantic embeddings
indexed in FAISS (IndexFlatIP) and rank_bm25 for keyword matching, merged
via reciprocal rank fusion. Indices are lazily initialized on first
retrieve() call.
"""

from __future__ import annotations

import logging
from typing import Any

from src.rag.knowledge_base import KNOWLEDGE_BASE, KnowledgeChunk

log = logging.getLogger(__name__)

# Sentence-transformers model: 384-dim, fast, good quality
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class RAGProvider:
    """Hybrid FAISS + BM25 retrieval-augmented generation provider.

    Dense retrieval via sentence-transformers (384-dim semantic embeddings)
    combined with BM25 keyword matching. Results merged via reciprocal rank
    fusion for robust retrieval across both semantic and lexical queries.
    """

    def __init__(self):
        self._chunks: list[KnowledgeChunk] = KNOWLEDGE_BASE
        self._bm25 = None
        self._faiss_index = None
        self._embedder = None
        self._np = None
        self._initialized = False

    def _initialize(self) -> None:
        """Build BM25 and FAISS indices from the knowledge base."""
        if self._initialized:
            return

        import faiss
        import numpy as np
        from rank_bm25 import BM25Okapi
        from sentence_transformers import SentenceTransformer

        self._np = np

        texts = [self._chunk_text(c) for c in self._chunks]

        # BM25 index
        tokenized = [t.lower().split() for t in texts]
        self._bm25 = BM25Okapi(tokenized)

        # Sentence-transformer embeddings + FAISS index
        self._embedder = SentenceTransformer(_EMBEDDING_MODEL)
        embeddings = self._embedder.encode(
            texts, normalize_embeddings=True, show_progress_bar=False,
        ).astype(np.float32)

        dim = embeddings.shape[1]
        self._faiss_index = faiss.IndexFlatIP(dim)
        self._faiss_index.add(embeddings)

        self._initialized = True
        log.info(
            "RAG indices built: %d chunks, embedding dim=%d (model=%s)",
            len(self._chunks), dim, _EMBEDDING_MODEL,
        )

    @staticmethod
    def _chunk_text(chunk: KnowledgeChunk) -> str:
        """Combine chunk fields into a single searchable text."""
        return f"{chunk.title}. {chunk.category}. {chunk.text}"

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve top-k relevant knowledge chunks via hybrid search.

        Runs BM25 keyword search and FAISS semantic search in parallel,
        then merges results using reciprocal rank fusion.

        Parameters
        ----------
        query : str
            Natural language query.
        top_k : int
            Number of chunks to return.

        Returns
        -------
        list[dict]
            Each dict: {id, title, source, category, text, relevance_score}.
        """
        self._initialize()

        n = len(self._chunks)
        k_retrieve = min(n, top_k * 3)  # over-retrieve for fusion

        # BM25 retrieval
        bm25_scores = self._bm25.get_scores(query.lower().split())
        bm25_ranking = self._np.argsort(bm25_scores)[::-1][:k_retrieve]

        # FAISS semantic retrieval
        query_emb = self._embedder.encode(
            [query], normalize_embeddings=True, show_progress_bar=False,
        ).astype(self._np.float32)
        faiss_scores, faiss_indices = self._faiss_index.search(query_emb, k_retrieve)
        faiss_ranking = faiss_indices[0]

        # Reciprocal Rank Fusion (RRF)
        rrf_k = 60  # standard RRF constant
        rrf_scores: dict[int, float] = {}

        for rank, idx in enumerate(bm25_ranking):
            idx = int(idx)
            rrf_scores[idx] = rrf_scores.get(idx, 0) + 1.0 / (rrf_k + rank + 1)

        for rank, idx in enumerate(faiss_ranking):
            idx = int(idx)
            if idx < 0:  # FAISS can return -1 for empty results
                continue
            rrf_scores[idx] = rrf_scores.get(idx, 0) + 1.0 / (rrf_k + rank + 1)

        # Sort by RRF score and take top_k
        sorted_indices = sorted(
            rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True,
        )
        top_indices = sorted_indices[:top_k]

        # Normalize scores to 0-1 range
        if top_indices:
            max_score = rrf_scores[top_indices[0]]
            min_score = rrf_scores[top_indices[-1]] if len(top_indices) > 1 else max_score
        else:
            max_score = min_score = 1.0

        results = []
        for idx in top_indices:
            chunk = self._chunks[idx]
            raw_score = rrf_scores[idx]
            if max_score > min_score:
                normalized = 0.5 + 0.5 * (raw_score - min_score) / (max_score - min_score)
            else:
                normalized = 1.0

            results.append({
                "id": chunk.id,
                "title": chunk.title,
                "source": chunk.source,
                "category": chunk.category,
                "text": chunk.text,
                "relevance_score": round(normalized, 4),
            })

        return results

    def retrieve_by_category(
        self, query: str, category: str, top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Retrieve chunks filtered to a specific category."""
        all_results = self.retrieve(query, top_k=top_k * 3)
        filtered = [r for r in all_results if r["category"] == category]
        return filtered[:top_k]

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def categories(self) -> list[str]:
        return sorted(set(c.category for c in self._chunks))

    @property
    def embedding_model(self) -> str:
        return _EMBEDDING_MODEL

    @property
    def embedding_dim(self) -> int:
        if self._faiss_index is not None:
            return self._faiss_index.d
        return 384  # default for all-MiniLM-L6-v2
