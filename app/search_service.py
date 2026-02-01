"""
Search Service for Personal Semantic Memory System.

This module orchestrates:
  - Stage A: FAISS vector retrieval (semantic search)
  - Handoff to rag_answerer.py for extractive QA (Stages B-D)

The retrieval layer is intentionally simple and stable.
All answer-layer intelligence lives in rag_answerer.py.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

# Import startup to trigger auto-initialization (migrations, etc.)
import app.startup  # noqa: F401

from app.config import INDEX_PATH, RESEARCH_PATH, ensure_data_dir
from app.embeddings import EmbeddingGenerator
from app.query_intent import QueryIntent, classify_query
from app.rag_answerer import (
    extract_best_answer,
    normalize_whitespace,
    fix_pdf_spacing,
    EvidenceConfidence,
)
from app.research_store import ResearchEntry, ResearchStore
from app.vector_store import FAISSVectorStore

# Import document utilities for source highlighting
try:
    from app.document_utils import find_answer_location
    DOCUMENT_UTILS_AVAILABLE = True
except ImportError:
    DOCUMENT_UTILS_AVAILABLE = False

logger = logging.getLogger("rag")


class SearchService:
    """
    Main search service for Synapse queries.
    
    Pipeline:
    1. Embed query and retrieve top-k chunks from FAISS
    2. Pass chunks to extractive QA layer
    3. Return answer + source documents
    """
    
    def __init__(self, index_path: Path = INDEX_PATH, research_path: Path = RESEARCH_PATH) -> None:
        ensure_data_dir()
        self.embedder = EmbeddingGenerator()
        self.store = FAISSVectorStore.load(index_path)
        self.research = ResearchStore.load_or_create(research_path, self.store.dim)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Basic search returning ranked document results (no answer extraction)."""
        query = query.strip()
        if not query:
            return []

        results = self._retrieve(query, k=max(top_k * 3, 10))
        if not results:
            return []

        results.sort(key=lambda item: item.get("final_score", 0), reverse=True)
        return results[:top_k]

    def answer(self, query: str, top_k: int = 6) -> dict[str, Any]:
        """
        Main entry point for Synapse factual recall.
        
        This is the "I know this fact exists somewhere — find it" interface.
        Returns a short, direct, extractive answer when possible.
        """
        intent = classify_query(query)
        
        # Stage A: FAISS retrieval
        results = self._retrieve(query, k=max(top_k * 4, 20))
        
        if not results:
            return self._empty_response(intent)
        
        # Build document list for UI (always available)
        documents = self._build_document_list(results, limit=top_k)
        
        # For exploratory queries, skip answer extraction
        if intent == QueryIntent.FULLTEXT:
            logger.debug("Exploratory query '%s' — showing documents only.", query)
            return self._documents_only_response(documents, intent)
        
        # Prepare top chunks for extraction
        top_chunks = self._prepare_chunks_for_extraction(results[:8])
        
        # Stages B-D: Extractive QA
        answer_payload = extract_best_answer(query=query, chunks=top_chunks)
        
        # If extraction found an answer
        if answer_payload.get("answerable", False):
            answer_text = answer_payload.get("answer", "")
            filepath = answer_payload.get("filepath", documents[0].get("filepath", "") if documents else "")
            
            response = {
                "answer": answer_text,
                "confidence": answer_payload.get("confidence", 0.0),
                "confidence_level": _to_str(answer_payload.get("confidence_level", EvidenceConfidence.NONE)),
                "source": answer_payload.get("source", documents[0].get("filename", "") if documents else ""),
                "filepath": filepath,
                "mode": intent.value,
                "answerable": True,
                "documents": documents,
            }
            
            # Add source location info for highlighting
            if DOCUMENT_UTILS_AVAILABLE and answer_text and filepath:
                location = find_answer_location(filepath, answer_text)
                if location:
                    response["source_page"] = location.get("page")
                    response["source_context"] = location.get("context")
            
            # Write to research memory
            self._write_research_entry(query, answer_text, results[:1])
            return response
        
        # Extraction failed — return documents with abstain message
        return {
            "answer": answer_payload.get("answer", "Answer not clearly found in your indexed documents."),
            "confidence": 0.0,
            "confidence_level": "none",
            "source": documents[0].get("filename", "") if documents else "",
            "filepath": documents[0].get("filepath", "") if documents else "",
            "mode": intent.value,
            "answerable": False,
            "documents": documents,
        }

    def _retrieve(self, query: str, k: int) -> list[dict[str, Any]]:
        """
        Stage A: FAISS retrieval with hybrid scoring.
        
        Combines:
        - Semantic similarity (cosine from FAISS)
        - Keyword overlap
        - Length score (slight preference for longer chunks)
        """
        q_emb = self.embedder.embed([query])
        results = self.store.search(q_emb, k=k)
        
        q_terms = _tokenize(query)
        for result in results:
            text = result.get("text", "")
            doc_terms = _tokenize(text)
            overlap = _keyword_overlap(q_terms, doc_terms)
            length_score = _length_score(len(text.split()))
            # Hybrid score: semantic + keyword overlap + length
            result["final_score"] = result["score"] + 0.4 * overlap + 0.1 * length_score
        
        return results

    def _prepare_chunks_for_extraction(self, results: list[dict], max_words: int = 400) -> list[dict[str, Any]]:
        """Prepare chunks for extraction, limiting total word count."""
        prepared = []
        remaining = max_words
        
        for result in results:
            text = result.get("text", "")
            words = text.split()
            if not words:
                continue
            
            if len(words) > remaining:
                words = words[:remaining]
            
            prepared.append({
                **result,
                "text": " ".join(words),
            })
            
            remaining -= len(words)
            if remaining <= 0:
                break
        
        return prepared

    def _build_document_list(self, results: list[dict], limit: int) -> list[dict[str, Any]]:
        """Build unique document list for UI display."""
        seen_filepaths: set[str] = set()
        documents: list[dict[str, Any]] = []

        for result in results:
            filepath = result.get("filepath", "")
            if not filepath or filepath in seen_filepaths:
                continue
            seen_filepaths.add(filepath)

            text = normalize_whitespace(fix_pdf_spacing(result.get("text", "")))
            preview = _make_preview(text, max_words=20)

            documents.append({
                "filepath": filepath,
                "filename": result.get("filename", ""),
                "preview": preview,
                "score": float(result.get("final_score", result.get("score", 0.0))),
            })

            if len(documents) >= limit:
                break

        return documents

    def _documents_only_response(
        self,
        documents: list[dict],
        intent: QueryIntent,
    ) -> dict[str, Any]:
        """Response for exploratory queries — documents only, no answer."""
        best = documents[0] if documents else {}
        return {
            "answer": "",
            "confidence": 0.0,
            "confidence_level": "none",
            "source": best.get("filename", ""),
            "filepath": best.get("filepath", ""),
            "mode": intent.value,
            "answerable": False,
            "documents": documents,
        }

    def _empty_response(self, intent: QueryIntent) -> dict[str, Any]:
        """Response when no results found."""
        return {
            "answer": "",
            "confidence": 0.0,
            "confidence_level": "none",
            "source": "",
            "filepath": "",
            "mode": intent.value,
            "answerable": False,
            "documents": [],
        }

    def _write_research_entry(self, query: str, answer: str, top_results: list[dict[str, Any]]) -> None:
        """Write successful Q&A to research memory."""
        if not top_results or not answer:
            return

        top = top_results[0]
        entry_text = f"Query: {query}\nAnswer: {answer}"
        key = f"{query.lower()}|{top.get('filepath','')}|{top.get('text','')[:200]}"

        entry = ResearchEntry(
            key=key,
            query=query,
            answer=answer,
            filename=top.get("filename", ""),
            filepath=top.get("filepath", ""),
            text=entry_text,
        )
        embedding = self.embedder.embed([entry_text])
        if self.research.add_entry(embedding, entry):
            self.research.save()

    def answer_streaming(
        self,
        query: str,
        on_documents: Callable[[list[dict]], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        on_answer_token: Callable[[str], None] | None = None,
        on_complete: Callable[[dict], None] | None = None,
        top_k: int = 6,
    ) -> dict[str, Any]:
        """
        Streaming version of answer() with progressive callbacks.
        
        Args:
            query: The search query
            on_documents: Called when documents are retrieved (before extraction)
            on_status: Called with status updates ("Searching...", "Extracting...")
            on_answer_token: Called for each character of the answer (typewriter effect)
            on_complete: Called when search is complete with full result
            top_k: Number of results to return
        
        Returns:
            Same payload as answer()
        """
        if on_status:
            on_status("Searching...")
        
        intent = classify_query(query)
        
        # Stage A: FAISS retrieval
        results = self._retrieve(query, k=max(top_k * 4, 20))
        
        if not results:
            result = self._empty_response(intent)
            if on_complete:
                on_complete(result)
            return result
        
        # Build document list and notify UI immediately
        documents = self._build_document_list(results, limit=top_k)
        if on_documents:
            on_documents(documents)
        
        # For exploratory queries, skip answer extraction
        if intent == QueryIntent.FULLTEXT:
            result = self._documents_only_response(documents, intent)
            if on_complete:
                on_complete(result)
            return result
        
        if on_status:
            on_status("Extracting answer...")
        
        # Prepare chunks and extract answer
        top_chunks = self._prepare_chunks_for_extraction(results[:8])
        answer_payload = extract_best_answer(query=query, chunks=top_chunks)
        
        # Build final response
        if answer_payload.get("answerable", False):
            answer_text = answer_payload.get("answer", "")
            filepath = answer_payload.get("filepath", documents[0].get("filepath", "") if documents else "")
            
            response = {
                "answer": answer_text,
                "confidence": answer_payload.get("confidence", 0.0),
                "confidence_level": _to_str(answer_payload.get("confidence_level", EvidenceConfidence.NONE)),
                "source": answer_payload.get("source", documents[0].get("filename", "") if documents else ""),
                "filepath": filepath,
                "mode": intent.value,
                "answerable": True,
                "documents": documents,
            }
            
            # Add source location info
            if DOCUMENT_UTILS_AVAILABLE and answer_text and filepath:
                location = find_answer_location(filepath, answer_text)
                if location:
                    response["source_page"] = location.get("page")
                    response["source_context"] = location.get("context")
            
            # Stream the answer character by character
            if on_answer_token and answer_text:
                for char in answer_text:
                    on_answer_token(char)
            
            self._write_research_entry(query, answer_text, results[:1])
        else:
            response = {
                "answer": answer_payload.get("answer", "Answer not clearly found in your indexed documents."),
                "confidence": 0.0,
                "confidence_level": "none",
                "source": documents[0].get("filename", "") if documents else "",
                "filepath": documents[0].get("filepath", "") if documents else "",
                "mode": intent.value,
                "answerable": False,
                "documents": documents,
            }
        
        if on_complete:
            on_complete(response)
        
        return response


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase words (3+ chars)."""
    return {t for t in re.findall(r"\w+", text.lower()) if len(t) > 2}


def _keyword_overlap(query_terms: set[str], doc_terms: set[str]) -> float:
    """Calculate keyword overlap ratio."""
    if not query_terms:
        return 0.0
    return len(query_terms & doc_terms) / len(query_terms)


def _length_score(word_count: int) -> float:
    """Score based on chunk length (slight preference for longer chunks)."""
    if word_count <= 0:
        return 0.0
    return min(word_count / 200.0, 1.0)


def _make_preview(text: str, max_words: int = 20) -> str:
    """Create a short preview snippet."""
    words = text.split()[:max_words]
    preview = " ".join(words)
    if len(text.split()) > max_words:
        preview += "…"
    return preview


def _to_str(confidence_level: EvidenceConfidence | str) -> str:
    """Convert confidence level to string."""
    if hasattr(confidence_level, "value"):
        return confidence_level.value
    return str(confidence_level)
