#!/usr/bin/env python3
"""
Document Watcher for Incremental Indexing.

Watches the /docs folder for new or modified files and automatically
updates the FAISS index without requiring a full rebuild.

Usage:
    python scripts/watcher.py

Features:
- Watches for new files
- Watches for modified files
- Watches for deleted files
- Updates index incrementally
- Supports PDF, DOCX, TXT files
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    print("⚠️  watchdog not installed. Install with: pip install watchdog")

from app.config import DOCS_PATH, DATA_DIR, INDEX_PATH, ensure_data_dir
from app.ingestion import DocumentIngester
from app.chunker import chunk_by_sentences
from app.embeddings import EmbeddingGenerator
from app.vector_store import FAISSVectorStore


# File to track indexed documents
MANIFEST_PATH = DATA_DIR / "index_manifest.json"


class IndexManifest:
    """Track which files have been indexed and their hashes."""
    
    def __init__(self):
        self.manifest: dict[str, dict] = {}
        self.load()
    
    def load(self):
        """Load manifest from disk."""
        if MANIFEST_PATH.exists():
            try:
                with open(MANIFEST_PATH, "r") as f:
                    self.manifest = json.load(f)
            except Exception as e:
                print(f"⚠️  Failed to load manifest: {e}")
                self.manifest = {}
    
    def save(self):
        """Save manifest to disk."""
        ensure_data_dir()
        with open(MANIFEST_PATH, "w") as f:
            json.dump(self.manifest, f, indent=2)
    
    def get_file_hash(self, filepath: Path) -> str:
        """Calculate hash of a file."""
        hasher = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def needs_indexing(self, filepath: Path) -> bool:
        """Check if a file needs to be (re)indexed."""
        if not filepath.exists():
            return False
        
        key = str(filepath)
        if key not in self.manifest:
            return True
        
        current_hash = self.get_file_hash(filepath)
        return self.manifest[key].get("hash") != current_hash
    
    def mark_indexed(self, filepath: Path, chunk_count: int):
        """Mark a file as indexed."""
        key = str(filepath)
        self.manifest[key] = {
            "hash": self.get_file_hash(filepath),
            "indexed_at": datetime.now().isoformat(),
            "chunk_count": chunk_count,
        }
        self.save()
    
    def mark_deleted(self, filepath: Path):
        """Mark a file as deleted."""
        key = str(filepath)
        if key in self.manifest:
            del self.manifest[key]
            self.save()
    
    def get_all_indexed_files(self) -> set[str]:
        """Get all indexed file paths."""
        return set(self.manifest.keys())


class IncrementalIndexer:
    """Handles incremental index updates."""
    
    def __init__(self):
        self.manifest = IndexManifest()
        self.ingester = DocumentIngester(str(DOCS_PATH))
        self.embedder = EmbeddingGenerator()
        self.store: FAISSVectorStore | None = None
        self._load_or_create_store()
    
    def _load_or_create_store(self):
        """Load existing store or create new one."""
        try:
            self.store = FAISSVectorStore.load(INDEX_PATH)
            print(f"✅ Loaded existing index ({self.store.index.ntotal} vectors)")
        except Exception:
            # Will create on first add
            self.store = None
    
    def index_file(self, filepath: Path) -> int:
        """Index a single file. Returns number of chunks added."""
        if not filepath.exists():
            return 0
        
        print(f"📄 Indexing: {filepath.name}")
        
        # Ingest document
        try:
            content = self.ingester._read_file(filepath)
            if not content or len(content.split()) < 10:
                print(f"   ⚠️  No content extracted")
                return 0
        except Exception as e:
            print(f"   ❌ Failed to extract: {e}")
            return 0
        
        # Chunk
        chunks = list(chunk_by_sentences(content, target_words=200, overlap_words=40))
        if not chunks:
            print(f"   ⚠️  No chunks produced")
            return 0
        
        # Prepare metadata
        texts = []
        metas = []
        for i, chunk_text in enumerate(chunks):
            if len(chunk_text.split()) < 10:
                continue
            texts.append(chunk_text)
            metas.append({
                "text": chunk_text,
                "filename": filepath.name,
                "filepath": str(filepath),
                "chunk_index": i,
            })
        
        if not texts:
            return 0
        
        # Embed
        embeddings = self.embedder.embed(texts)
        
        # Add to store
        if self.store is None:
            self.store = FAISSVectorStore(embeddings.shape[1])
        
        self.store.add(embeddings, metas)
        self.store.save(INDEX_PATH)
        
        # Update manifest
        self.manifest.mark_indexed(filepath, len(texts))
        
        print(f"   ✅ Added {len(texts)} chunks")
        return len(texts)
    
    def remove_file(self, filepath: Path):
        """Remove a file from the index (marks as deleted)."""
        print(f"🗑️  Removing from index: {filepath.name}")
        self.manifest.mark_deleted(filepath)
        # Note: FAISS doesn't support deletion, so we just mark in manifest
        # Full rebuild will be needed to actually remove vectors
    
    def check_and_index_all(self):
        """Check all files and index those that need it."""
        if not DOCS_PATH.exists():
            print(f"⚠️  Docs folder not found: {DOCS_PATH}")
            return
        
        indexed_count = 0
        
        for filepath in DOCS_PATH.iterdir():
            if filepath.suffix.lower() in {".pdf", ".docx", ".txt", ".md"}:
                if self.manifest.needs_indexing(filepath):
                    chunks = self.index_file(filepath)
                    indexed_count += chunks
        
        if indexed_count > 0:
            print(f"\n✅ Indexed {indexed_count} new chunks")
        else:
            print("✅ Index is up to date")


class DocumentEventHandler(FileSystemEventHandler):
    """Handle file system events for automatic indexing."""
    
    def __init__(self, indexer: IncrementalIndexer):
        self.indexer = indexer
        self._debounce: dict[str, float] = {}
    
    def _should_process(self, path: str) -> bool:
        """Check if we should process this event (debounce)."""
        now = time.time()
        last = self._debounce.get(path, 0)
        if now - last < 2.0:  # 2 second debounce
            return False
        self._debounce[path] = now
        return True
    
    def _is_valid_file(self, path: str) -> bool:
        """Check if file should be indexed."""
        p = Path(path)
        return p.suffix.lower() in {".pdf", ".docx", ".txt", ".md"}
    
    def on_created(self, event):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return
        if self._should_process(event.src_path):
            print(f"\n📥 New file detected: {Path(event.src_path).name}")
            self.indexer.index_file(Path(event.src_path))
    
    def on_modified(self, event):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return
        if self._should_process(event.src_path):
            filepath = Path(event.src_path)
            if self.indexer.manifest.needs_indexing(filepath):
                print(f"\n📝 File modified: {filepath.name}")
                self.indexer.index_file(filepath)
    
    def on_deleted(self, event):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return
        print(f"\n🗑️  File deleted: {Path(event.src_path).name}")
        self.indexer.remove_file(Path(event.src_path))


def run_watcher():
    """Run the file watcher."""
    print("=" * 50)
    print("📂 Document Watcher")
    print("=" * 50)
    print()
    print(f"Watching: {DOCS_PATH}")
    print("Supported: .pdf, .docx, .txt, .md")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    # Ensure docs folder exists
    DOCS_PATH.mkdir(parents=True, exist_ok=True)
    
    # Initialize indexer
    indexer = IncrementalIndexer()
    
    # Check existing files
    print("🔍 Checking for new/modified files...")
    indexer.check_and_index_all()
    print()
    
    # Start watcher
    event_handler = DocumentEventHandler(indexer)
    observer = Observer()
    observer.schedule(event_handler, str(DOCS_PATH), recursive=False)
    observer.start()
    
    print("👀 Watching for changes...")
    print()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping watcher...")
        observer.stop()
    
    observer.join()


def main():
    """Main entry point."""
    if not WATCHDOG_AVAILABLE:
        print("Cannot run watcher without watchdog installed.")
        print("Install with: pip install watchdog")
        sys.exit(1)
    
    run_watcher()


if __name__ == "__main__":
    main()
