from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.chunker import chunk
from app.config import DOCS_DIR, INDEX_PATH, ensure_data_dir
from app.embeddings import EmbeddingGenerator
from app.ingestion import DocumentIngester
from app.vector_store import FAISSVectorStore


def _detect_section_type(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "body"
    first = lines[0]
    if len(first) <= 40 and first.isupper():
        return "heading"
    if first.endswith(":"):
        return "label"
    if first.lower().startswith(("summary", "overview", "abstract")):
        return "summary"
    return "body"


def build_index() -> None:
    ensure_data_dir()

    print(f"📥 Ingesting documents from {DOCS_DIR}...")
    ingester = DocumentIngester(DOCS_DIR)
    docs = ingester.ingest_all()

    print("✂️ Chunking documents...")
    texts: list[str] = []
    metas: list[dict] = []

    for doc in docs:
        for c in chunk(doc["content"], chunk_size=240, overlap=40):
            if len(c.split()) < 10:
                continue
            texts.append(c)
            metas.append(
                {
                    "text": c,
                    "filename": doc["filename"],
                    "filepath": doc["filepath"],
                    "section_type": _detect_section_type(c),
                }
            )

    if not texts:
        raise RuntimeError(
            "No text chunks produced. Check ingestion output or lower chunk size."
        )

    print(f"🧠 Generating embeddings for {len(texts)} chunks...")
    embedder = EmbeddingGenerator()
    embeddings = embedder.embed(texts)

    if embeddings.ndim != 2:
        raise RuntimeError(f"Invalid embedding shape: {embeddings.shape}")

    print(f"💾 Saving FAISS index to {INDEX_PATH}...")
    store = FAISSVectorStore(embeddings.shape[1])
    store.add(embeddings, metas)
    store.save(INDEX_PATH)

    print(f"✅ Indexed {len(texts)} chunks from {len(docs)} files")


def main() -> None:
    try:
        build_index()
    except Exception as exc:
        print(f"❌ Index build failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
