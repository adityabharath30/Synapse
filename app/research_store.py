from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.vector_store import FAISSVectorStore


@dataclass(frozen=True)
class ResearchEntry:
    key: str
    query: str
    answer: str
    filename: str
    filepath: str
    text: str


class ResearchStore:
    def __init__(self, path: Path, dim: int) -> None:
        self.path = path
        self.store = FAISSVectorStore(dim)
        self._keys: set[str] = set()

    @classmethod
    def load_or_create(cls, path: Path, dim: int) -> "ResearchStore":
        if path.with_suffix(".faiss").exists() and path.with_suffix(".pkl").exists():
            store = cls(path, dim)
            store.store = FAISSVectorStore.load(path)
            store._keys = {meta.get("key", "") for meta in store.store.metadata}
            return store

        return cls(path, dim)

    def add_entry(self, embedding: np.ndarray, entry: ResearchEntry) -> bool:
        if entry.key in self._keys:
            return False

        metadata = {
            "key": entry.key,
            "query": entry.query,
            "answer": entry.answer,
            "filename": entry.filename,
            "filepath": entry.filepath,
            "text": entry.text,
        }
        self.store.add(embedding, [metadata])
        self._keys.add(entry.key)
        return True

    def search(self, query_embedding: np.ndarray, k: int = 5) -> list[dict[str, Any]]:
        return self.store.search(query_embedding, k=k)

    def save(self) -> None:
        self.store.save(self.path)
