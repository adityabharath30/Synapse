"""
Embedding Generator with Model Caching.

Uses SentenceTransformers for semantic embeddings.
The model is cached as a singleton for faster subsequent loads.
"""
from __future__ import annotations

import logging
import threading

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("rag")

# Singleton model cache
_model_cache: dict[str, SentenceTransformer] = {}
_cache_lock = threading.Lock()

DEFAULT_MODEL = "multi-qa-MiniLM-L6-cos-v1"


def get_cached_model(model_name: str = DEFAULT_MODEL) -> SentenceTransformer:
    """
    Get or load a cached SentenceTransformer model.
    
    Thread-safe singleton pattern ensures the model is loaded only once
    across all EmbeddingGenerator instances.
    """
    with _cache_lock:
        if model_name not in _model_cache:
            logger.info("Loading embedding model: %s", model_name)
            try:
                _model_cache[model_name] = SentenceTransformer(model_name)
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.error("Failed to load model: %s", e)
                raise
        return _model_cache[model_name]


def preload_model(model_name: str = DEFAULT_MODEL) -> None:
    """
    Pre-load the embedding model in background.
    Call this early in app startup for faster first search.
    """
    def _load():
        try:
            get_cached_model(model_name)
        except Exception as e:
            logger.error("Background model load failed: %s", e)
    
    thread = threading.Thread(target=_load, daemon=True)
    thread.start()


class EmbeddingGenerator:
    """
    Generate embeddings for text using SentenceTransformers.
    
    Uses a cached singleton model for fast repeated calls.
    """
    
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model: SentenceTransformer | None = None
    
    @property
    def model(self) -> SentenceTransformer:
        """Lazy-load the model from cache."""
        if self._model is None:
            self._model = get_cached_model(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        Generate embeddings for a list of texts.
        
        Returns:
            numpy array of shape (len(texts), embedding_dim)
        """
        if not texts:
            return np.zeros((0, 0), dtype="float32")

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.array(embeddings, dtype="float32")
    
    @property
    def dimension(self) -> int:
        """Get the embedding dimension."""
        return self.model.get_sentence_embedding_dimension()