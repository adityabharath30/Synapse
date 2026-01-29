from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

import faiss
import numpy as np


class FAISSVectorStore:
    def __init__(self, dim: int) -> None:
        if dim <= 0:
            raise ValueError("Embedding dimension must be positive.")
        self.index = faiss.IndexFlatIP(dim)
        self.metadata: list[dict[str, Any]] = []

    @property
    def dim(self) -> int:
        return self.index.d

    def add(self, embeddings: np.ndarray, metadatas: list[dict[str, Any]]) -> None:
        if len(metadatas) != len(embeddings):
            raise ValueError("Embeddings and metadata length mismatch.")
        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype("float32")
        if embeddings.ndim != 2 or embeddings.shape[1] != self.index.d:
            raise ValueError("Embeddings shape does not match index dimension.")

        self.index.add(embeddings)
        self.metadata.extend(metadatas)

    def search(self, query_embedding: np.ndarray, k: int = 5) -> list[dict[str, Any]]:
        if self.index.ntotal == 0:
            return []
        if query_embedding.ndim != 2:
            raise ValueError("Query embedding must be 2D (batch, dim).")

        scores, ids = self.index.search(query_embedding, k)
        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx == -1:
                continue
            meta = dict(self.metadata[idx])
            results.append(
                {
                    "score": float(score),
                    "text": meta.get("text", ""),
                    "filename": meta.get("filename", ""),
                    "filepath": meta.get("filepath", ""),
                    **meta,
                }
            )
        return results

    def save(self, path: str | Path) -> None:
        base = Path(path)
        faiss.write_index(self.index, str(base.with_suffix(".faiss")))
        with open(base.with_suffix(".pkl"), "wb") as handle:
            pickle.dump(self.metadata, handle)

    @classmethod
    def load(cls, path: str | Path) -> "FAISSVectorStore":
        base = Path(path)
        faiss_path = base.with_suffix(".faiss")
        meta_path = base.with_suffix(".pkl")

        if not faiss_path.exists() or not meta_path.exists():
            raise RuntimeError("FAISS index not found — run scripts/index_builder.py")

        index = faiss.read_index(str(faiss_path))
        with open(meta_path, "rb") as handle:
            metadata = pickle.load(handle)

        store = cls(index.d)
        store.index = index
        store.metadata = metadata
        return store
