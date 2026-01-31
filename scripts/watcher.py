#!/usr/bin/env python3
"""
Device-Wide Document Watcher with Scheduled Scanning.

Watches configured directories for new or modified files and automatically
updates the FAISS index. Supports both real-time watching and scheduled
full scans for comprehensive indexing.

Usage:
    python scripts/watcher.py              # Run watcher with default config
    python scripts/watcher.py --scan-now   # Run immediate full scan
    python scripts/watcher.py --stats      # Show indexing statistics

Features:
- Watches multiple directories from scanner_config.yaml
- Real-time file change detection with debouncing
- Scheduled full scans (default: every 24 hours)
- Differential indexing (only processes changed files)
- Security filtering (respects exclusion patterns)
- Supports all file types including images via vision API
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    print("⚠️  watchdog not installed. Install with: pip install watchdog")

from app.config import INDEX_PATH, DATA_DIR, ensure_data_dir
from app.ingestion import DocumentIngester, SUPPORTED_EXTENSIONS, IMAGE_EXTENSIONS
from app.chunker import chunk
from app.embeddings import EmbeddingGenerator
from app.vector_store import FAISSVectorStore
from app.scanner import FileScanner, ScanManifest, ScannedFile
from app.scanner_config import get_config, reload_config, ScannerConfig

# Import security/audit if available
try:
    from app.security import get_audit_logger
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False


class DeviceIndexer:
    """
    Handles indexing files from across the device.
    
    Supports both incremental (single file) and batch indexing modes.
    Uses differential indexing to skip unchanged files.
    Includes audit logging for transparency.
    """
    
    def __init__(self, config: ScannerConfig | None = None):
        self.config = config or get_config()
        self.scanner = FileScanner(self.config)
        self.manifest = self.scanner.manifest
        
        # Use local_only mode from config
        local_only = getattr(self.config, 'local_only_mode', False)
        self.ingester = DocumentIngester(Path.home() / "Documents", local_only=local_only)
        
        self.embedder = EmbeddingGenerator()
        self.store: FAISSVectorStore | None = None
        self._load_or_create_store()
        self._lock = threading.Lock()
        
        # Initialize audit logger if enabled
        self.audit = None
        if AUDIT_AVAILABLE and getattr(self.config, 'enable_audit_logging', True):
            try:
                self.audit = get_audit_logger(DATA_DIR)
            except Exception:
                pass
    
    def _load_or_create_store(self) -> None:
        """Load existing vector store or prepare to create new one."""
        try:
            self.store = FAISSVectorStore.load(INDEX_PATH)
            print(f"✅ Loaded existing index ({self.store.index.ntotal} vectors)")
        except Exception:
            self.store = None
            print("ℹ️  No existing index found, will create on first file")
    
    def index_file(self, file_path: Path, force: bool = False) -> int:
        """
        Index a single file.
        
        Args:
            file_path: Path to the file to index
            force: If True, index even if file hasn't changed
        
        Returns:
            Number of chunks added to the index.
        """
        with self._lock:
            if not file_path.exists():
                return 0
            
            # Check if indexing is needed
            if not force and not self.manifest.needs_indexing(file_path):
                return 0
            
            print(f"📄 Indexing: {file_path.name}")
            
            # Read file content
            try:
                content = self.ingester._read_file(file_path)
                if not content or len(content.split()) < 10:
                    print(f"   ⚠️  No content extracted from {file_path.name}")
                    return 0
            except Exception as e:
                print(f"   ❌ Failed to read {file_path.name}: {e}")
                return 0
            
            # Chunk the content
            chunks = list(chunk(content, chunk_size=240, overlap=40))
            if not chunks:
                print(f"   ⚠️  No chunks produced from {file_path.name}")
                return 0
            
            # Filter small chunks and prepare metadata
            texts = []
            metas = []
            for i, chunk_text in enumerate(chunks):
                if len(chunk_text.split()) < 10:
                    continue
                texts.append(chunk_text)
                metas.append({
                    "text": chunk_text,
                    "filename": file_path.name,
                    "filepath": str(file_path),
                    "chunk_index": i,
                    "indexed_at": datetime.now().isoformat(),
                })
            
            if not texts:
                return 0
            
            # Generate embeddings
            embeddings = self.embedder.embed(texts)
            
            # Add to vector store
            if self.store is None:
                self.store = FAISSVectorStore(embeddings.shape[1])
            
            self.store.add(embeddings, metas)
            self.store.save(INDEX_PATH)
            
            # Update manifest
            self.manifest.mark_indexed(file_path, len(texts))
            self.manifest.save()
            
            # Audit log
            if self.audit:
                self.audit.log_file_indexed(str(file_path), len(texts))
            
            print(f"   ✅ Added {len(texts)} chunks")
            return len(texts)
    
    def index_batch(self, files: list[ScannedFile]) -> tuple[int, int]:
        """
        Index a batch of files.
        
        Args:
            files: List of ScannedFile objects to index
        
        Returns:
            Tuple of (files_processed, total_chunks_added)
        """
        files_processed = 0
        total_chunks = 0
        
        for scanned_file in files:
            try:
                chunks = self.index_file(scanned_file.path)
                if chunks > 0:
                    files_processed += 1
                    total_chunks += chunks
                
                # Pause between files to avoid overwhelming system
                if self.config.batch_pause_seconds > 0:
                    time.sleep(self.config.batch_pause_seconds)
            
            except Exception as e:
                print(f"   ❌ Error indexing {scanned_file.path.name}: {e}")
        
        return files_processed, total_chunks
    
    def run_full_scan(self) -> tuple[int, int]:
        """
        Run a full scan of all configured directories.
        
        Returns:
            Tuple of (files_processed, total_chunks_added)
        """
        print("\n" + "=" * 60)
        print("🔍 Starting full device scan...")
        print("=" * 60)
        
        # Get list of files needing indexing
        files_to_index = list(self.scanner.scan_for_changes())
        
        if not files_to_index:
            print("✅ All files are up to date!")
            self.manifest.mark_full_scan_complete()
            return 0, 0
        
        print(f"📋 Found {len(files_to_index)} files to index")
        
        # Process in batches
        batch_size = self.config.batch_size
        files_processed = 0
        total_chunks = 0
        
        for i in range(0, len(files_to_index), batch_size):
            batch = files_to_index[i:i + batch_size]
            print(f"\n📦 Processing batch {i // batch_size + 1}/{(len(files_to_index) + batch_size - 1) // batch_size}")
            
            processed, chunks = self.index_batch(batch)
            files_processed += processed
            total_chunks += chunks
        
        # Check for deleted files
        deleted = self.scanner.find_deleted_files()
        if deleted:
            print(f"\n🗑️  Marking {len(deleted)} deleted files")
            for path in deleted:
                self.manifest.mark_deleted(Path(path))
            self.manifest.save()
        
        self.manifest.mark_full_scan_complete()
        
        print("\n" + "=" * 60)
        print(f"✅ Full scan complete!")
        print(f"   Files processed: {files_processed}")
        print(f"   Chunks added: {total_chunks}")
        print("=" * 60)
        
        return files_processed, total_chunks
    
    def remove_file(self, file_path: Path) -> None:
        """Mark a file as deleted in the manifest."""
        with self._lock:
            print(f"🗑️  Removing from index: {file_path.name}")
            self.manifest.mark_deleted(file_path)
            self.manifest.save()
            
            # Audit log
            if self.audit:
                self.audit.log_file_deleted(str(file_path))
            
            # Note: FAISS doesn't support deletion, vectors remain until rebuild
    
    def get_stats(self) -> dict:
        """Get indexing statistics."""
        stats = self.manifest.get_stats()
        if self.store:
            stats["vector_count"] = self.store.index.ntotal
        stats["scan_directories"] = [str(d) for d in self.config.get_scan_directories()]
        return stats


class MultiDirectoryEventHandler(FileSystemEventHandler):
    """
    Handle file system events for automatic indexing across multiple directories.
    
    Implements debouncing to batch rapid file changes.
    """
    
    def __init__(self, indexer: DeviceIndexer, config: ScannerConfig):
        self.indexer = indexer
        self.config = config
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._debounce_thread: threading.Thread | None = None
        self._running = True
    
    def start_debounce_processor(self) -> None:
        """Start background thread to process debounced events."""
        self._debounce_thread = threading.Thread(target=self._process_pending, daemon=True)
        self._debounce_thread.start()
    
    def stop(self) -> None:
        """Stop the debounce processor."""
        self._running = False
        if self._debounce_thread:
            self._debounce_thread.join(timeout=2)
    
    def _process_pending(self) -> None:
        """Background thread to process pending file changes."""
        while self._running:
            time.sleep(1)
            
            with self._lock:
                now = time.time()
                ready = [
                    path for path, timestamp in self._pending.items()
                    if now - timestamp >= self.config.watcher_debounce_seconds
                ]
                
                for path in ready:
                    del self._pending[path]
            
            # Process ready files outside the lock
            for path in ready:
                file_path = Path(path)
                if file_path.exists():
                    self.indexer.index_file(file_path)
    
    def _is_valid_file(self, path: str) -> bool:
        """Check if file should be indexed based on config."""
        file_path = Path(path)
        
        # Check extension
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return False
        
        # Check exclusions
        if self.config.is_file_excluded(file_path):
            return False
        
        # Check directory exclusions
        if self.config.is_directory_excluded(file_path.parent):
            return False
        
        return True
    
    def _queue_file(self, path: str) -> None:
        """Add file to pending queue with current timestamp."""
        with self._lock:
            self._pending[path] = time.time()
    
    def on_created(self, event):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return
        print(f"\n📥 New file detected: {Path(event.src_path).name}")
        self._queue_file(event.src_path)
    
    def on_modified(self, event):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return
        print(f"\n📝 File modified: {Path(event.src_path).name}")
        self._queue_file(event.src_path)
    
    def on_deleted(self, event):
        if event.is_directory or not self._is_valid_file(event.src_path):
            return
        print(f"\n🗑️  File deleted: {Path(event.src_path).name}")
        self.indexer.remove_file(Path(event.src_path))
    
    def on_moved(self, event):
        if event.is_directory:
            return
        
        # Handle source (treat as deleted)
        if self._is_valid_file(event.src_path):
            print(f"\n🗑️  File moved from: {Path(event.src_path).name}")
            self.indexer.remove_file(Path(event.src_path))
        
        # Handle destination (treat as created)
        if self._is_valid_file(event.dest_path):
            print(f"\n📥 File moved to: {Path(event.dest_path).name}")
            self._queue_file(event.dest_path)


class ScheduledScanner:
    """
    Runs periodic full scans at configured intervals.
    """
    
    def __init__(self, indexer: DeviceIndexer, config: ScannerConfig):
        self.indexer = indexer
        self.config = config
        self._thread: threading.Thread | None = None
        self._running = False
        self._next_scan: datetime | None = None
    
    def start(self) -> None:
        """Start the scheduled scanner."""
        if self.config.full_scan_interval_hours <= 0:
            print("ℹ️  Scheduled scanning disabled (interval = 0)")
            return
        
        self._running = True
        self._calculate_next_scan()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print(f"⏰ Scheduled scan every {self.config.full_scan_interval_hours} hours")
        print(f"   Next scan: {self._next_scan.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def stop(self) -> None:
        """Stop the scheduled scanner."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _calculate_next_scan(self) -> None:
        """Calculate when the next scan should run."""
        interval = timedelta(hours=self.config.full_scan_interval_hours)
        
        # Check last scan time from manifest
        last_scan_str = self.indexer.manifest.last_full_scan
        if last_scan_str:
            try:
                last_scan = datetime.fromisoformat(last_scan_str)
                self._next_scan = last_scan + interval
                
                # If next scan is in the past, schedule for soon
                if self._next_scan < datetime.now():
                    self._next_scan = datetime.now() + timedelta(minutes=5)
                return
            except ValueError:
                pass
        
        # No previous scan, schedule one in 5 minutes
        self._next_scan = datetime.now() + timedelta(minutes=5)
    
    def _run_loop(self) -> None:
        """Background loop to trigger scans."""
        while self._running:
            time.sleep(60)  # Check every minute
            
            if self._next_scan and datetime.now() >= self._next_scan:
                print(f"\n⏰ Scheduled scan triggered at {datetime.now().strftime('%H:%M:%S')}")
                self.indexer.run_full_scan()
                self._calculate_next_scan()
                if self._running:
                    print(f"⏰ Next scan: {self._next_scan.strftime('%Y-%m-%d %H:%M:%S')}")


def run_watcher() -> None:
    """Run the multi-directory file watcher with scheduled scanning."""
    if not WATCHDOG_AVAILABLE:
        print("Cannot run watcher without watchdog installed.")
        print("Install with: pip install watchdog")
        sys.exit(1)
    
    config = get_config()
    
    print("=" * 60)
    print("📂 Device-Wide Document Watcher")
    print("=" * 60)
    print()
    
    # Show configured directories
    scan_dirs = config.get_scan_directories()
    if not scan_dirs:
        print("❌ No scan directories configured or accessible!")
        print("   Edit scanner_config.yaml to add directories.")
        sys.exit(1)
    
    print("Watching directories:")
    for d in scan_dirs:
        print(f"  • {d}")
    print()
    print(f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    # Ensure data directory exists
    ensure_data_dir()
    
    # Initialize indexer
    indexer = DeviceIndexer(config)
    
    # Run initial check for new files
    print("🔍 Checking for new/modified files...")
    files_to_check = list(indexer.scanner.scan_for_changes())
    if files_to_check:
        print(f"   Found {len(files_to_check)} files to index")
        indexer.index_batch(files_to_check)
    else:
        print("   All files up to date")
    print()
    
    # Set up file watcher
    event_handler = MultiDirectoryEventHandler(indexer, config)
    event_handler.start_debounce_processor()
    
    observer = Observer()
    for scan_dir in scan_dirs:
        try:
            observer.schedule(
                event_handler,
                str(scan_dir),
                recursive=config.recursive
            )
            print(f"👀 Watching: {scan_dir}")
        except Exception as e:
            print(f"⚠️  Cannot watch {scan_dir}: {e}")
    
    observer.start()
    print()
    
    # Start scheduled scanner
    scheduler = ScheduledScanner(indexer, config)
    scheduler.start()
    print()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping watcher...")
        observer.stop()
        event_handler.stop()
        scheduler.stop()
    
    observer.join()
    print("Goodbye!")


def run_full_scan_now() -> None:
    """Run an immediate full scan without starting the watcher."""
    config = get_config()
    indexer = DeviceIndexer(config)
    indexer.run_full_scan()


def show_stats() -> None:
    """Display indexing statistics."""
    config = get_config()
    indexer = DeviceIndexer(config)
    stats = indexer.get_stats()
    
    print("=" * 60)
    print("📊 Indexing Statistics")
    print("=" * 60)
    print()
    print(f"Total files indexed: {stats.get('total_files', 0)}")
    print(f"Total chunks: {stats.get('total_chunks', 0)}")
    print(f"Total size: {stats.get('total_size_mb', 0)} MB")
    print(f"Vectors in index: {stats.get('vector_count', 'N/A')}")
    print()
    print("Scan directories:")
    for d in stats.get('scan_directories', []):
        print(f"  • {d}")
    print()
    if stats.get('last_full_scan'):
        print(f"Last full scan: {stats['last_full_scan']}")


def main() -> None:
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="Device-wide document watcher and indexer"
    )
    parser.add_argument(
        "--scan-now",
        action="store_true",
        help="Run immediate full scan without starting watcher"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show indexing statistics"
    )
    parser.add_argument(
        "--reload-config",
        action="store_true",
        help="Reload configuration from scanner_config.yaml"
    )
    
    args = parser.parse_args()
    
    if args.reload_config:
        reload_config()
        print("✅ Configuration reloaded")
    
    if args.stats:
        show_stats()
    elif args.scan_now:
        run_full_scan_now()
    else:
        run_watcher()


if __name__ == "__main__":
    main()
