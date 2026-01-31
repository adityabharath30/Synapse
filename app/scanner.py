"""
Device-Wide File Scanner.

Scans configured directories for indexable files while respecting
security exclusions and file size limits.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator, Iterator

from app.config import DATA_DIR, ensure_data_dir
from app.ingestion import IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS
from app.scanner_config import ScannerConfig, get_config

logger = logging.getLogger("rag.scanner")

# Manifest file for tracking scanned files
SCAN_MANIFEST_PATH = DATA_DIR / "scan_manifest.json"


@dataclass
class ScannedFile:
    """Represents a file discovered during scanning."""
    path: Path
    size_bytes: int
    modified_time: float
    file_hash: str | None = None
    is_image: bool = False


class ScanManifest:
    """
    Track scanned files and their states for differential indexing.
    
    Stores file hashes and modification times to detect changes
    without re-reading file contents.
    """
    
    def __init__(self, manifest_path: Path | None = None):
        self.manifest_path = manifest_path or SCAN_MANIFEST_PATH
        self.files: dict[str, dict] = {}
        self.last_full_scan: str | None = None
        self._load()
    
    def _load(self) -> None:
        """Load manifest from disk."""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.files = data.get("files", {})
                    self.last_full_scan = data.get("last_full_scan")
            except Exception as e:
                logger.warning("Failed to load scan manifest: %s", e)
                self.files = {}
    
    def save(self) -> None:
        """Save manifest to disk."""
        ensure_data_dir()
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump({
                    "files": self.files,
                    "last_full_scan": self.last_full_scan,
                }, f, indent=2)
        except Exception as e:
            logger.error("Failed to save scan manifest: %s", e)
    
    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """Compute MD5 hash of file contents."""
        hasher = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""
    
    def get_file_state(self, file_path: Path) -> dict | None:
        """Get stored state for a file."""
        return self.files.get(str(file_path))
    
    def needs_indexing(self, file_path: Path) -> bool:
        """
        Check if a file needs to be (re)indexed.
        
        Returns True if:
        - File is not in manifest (new file)
        - File modification time has changed
        - File hash has changed (if mtime changed)
        """
        key = str(file_path)
        
        if key not in self.files:
            return True
        
        try:
            stat = file_path.stat()
            stored = self.files[key]
            
            # Quick check: modification time
            if stat.st_mtime != stored.get("mtime"):
                # Verify with hash to avoid false positives from touched files
                current_hash = self.compute_file_hash(file_path)
                return current_hash != stored.get("hash")
            
            return False
        except OSError:
            return False
    
    def mark_indexed(
        self,
        file_path: Path,
        chunk_count: int,
        file_hash: str | None = None
    ) -> None:
        """Mark a file as successfully indexed."""
        try:
            stat = file_path.stat()
            self.files[str(file_path)] = {
                "hash": file_hash or self.compute_file_hash(file_path),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "indexed_at": datetime.now().isoformat(),
                "chunk_count": chunk_count,
            }
        except OSError as e:
            logger.warning("Failed to mark file as indexed: %s", e)
    
    def mark_deleted(self, file_path: Path) -> None:
        """Remove a file from the manifest."""
        key = str(file_path)
        if key in self.files:
            del self.files[key]
    
    def mark_full_scan_complete(self) -> None:
        """Record that a full scan was completed."""
        self.last_full_scan = datetime.now().isoformat()
        self.save()
    
    def get_indexed_files(self) -> set[str]:
        """Get all file paths that have been indexed."""
        return set(self.files.keys())
    
    def find_deleted_files(self, current_files: set[str]) -> set[str]:
        """Find files in manifest that no longer exist."""
        indexed = self.get_indexed_files()
        return indexed - current_files
    
    def get_stats(self) -> dict:
        """Get statistics about indexed files."""
        total_chunks = sum(f.get("chunk_count", 0) for f in self.files.values())
        total_size = sum(f.get("size", 0) for f in self.files.values())
        return {
            "total_files": len(self.files),
            "total_chunks": total_chunks,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "last_full_scan": self.last_full_scan,
        }


class FileScanner:
    """
    Scans configured directories for indexable files.
    
    Respects security exclusions and file size limits from configuration.
    """
    
    def __init__(self, config: ScannerConfig | None = None):
        self.config = config or get_config()
        self.manifest = ScanManifest()
    
    def scan_all(self) -> Generator[ScannedFile, None, None]:
        """
        Scan all configured directories for indexable files.
        
        Yields ScannedFile objects for each valid file found.
        """
        for scan_dir in self.config.get_scan_directories():
            logger.info("Scanning directory: %s", scan_dir)
            yield from self._scan_directory(scan_dir, depth=0)
    
    def scan_for_changes(self) -> Generator[ScannedFile, None, None]:
        """
        Scan for new or modified files only.
        
        Uses the manifest to skip unchanged files.
        """
        for scanned_file in self.scan_all():
            if self.manifest.needs_indexing(scanned_file.path):
                yield scanned_file
    
    def _scan_directory(
        self,
        directory: Path,
        depth: int
    ) -> Generator[ScannedFile, None, None]:
        """Recursively scan a directory for files."""
        # Check depth limit
        if self.config.max_depth > 0 and depth > self.config.max_depth:
            return
        
        # Check if directory is excluded
        if self.config.is_directory_excluded(directory):
            logger.debug("Skipping excluded directory: %s", directory)
            return
        
        try:
            entries = list(directory.iterdir())
        except PermissionError:
            logger.debug("Permission denied: %s", directory)
            return
        except OSError as e:
            logger.debug("Cannot read directory %s: %s", directory, e)
            return
        
        for entry in entries:
            try:
                # Handle symlinks
                if entry.is_symlink():
                    if not self.config.follow_symlinks:
                        continue
                    entry = entry.resolve()
                
                if entry.is_dir():
                    if self.config.recursive:
                        yield from self._scan_directory(entry, depth + 1)
                
                elif entry.is_file():
                    scanned = self._check_file(entry)
                    if scanned:
                        yield scanned
            
            except PermissionError:
                continue
            except OSError:
                continue
    
    def _check_file(self, file_path: Path) -> ScannedFile | None:
        """
        Check if a file should be indexed.
        
        Returns ScannedFile if valid, None if excluded.
        """
        # Check extension
        suffix = file_path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            return None
        
        # Check exclusion patterns
        if self.config.is_file_excluded(file_path):
            logger.debug("Skipping excluded file: %s", file_path.name)
            return None
        
        # Check file size
        if not self.config.is_file_size_valid(file_path):
            logger.debug("Skipping file (size out of range): %s", file_path.name)
            return None
        
        # Determine if it's an image
        is_image = suffix in IMAGE_EXTENSIONS
        
        # For images, check additional restrictions
        if is_image and not self.config.should_process_image(file_path):
            logger.debug("Skipping image (not in allowed dirs or too large): %s", file_path.name)
            return None
        
        try:
            stat = file_path.stat()
            return ScannedFile(
                path=file_path,
                size_bytes=stat.st_size,
                modified_time=stat.st_mtime,
                is_image=is_image,
            )
        except OSError:
            return None
    
    def get_all_current_files(self) -> set[str]:
        """Get set of all currently scannable file paths."""
        return {str(f.path) for f in self.scan_all()}
    
    def find_deleted_files(self) -> set[str]:
        """Find files that were indexed but no longer exist."""
        current = self.get_all_current_files()
        return self.manifest.find_deleted_files(current)
    
    def get_directory_stats(self) -> dict[str, int]:
        """Get file counts per scan directory."""
        stats = {}
        for scan_dir in self.config.get_scan_directories():
            count = sum(1 for _ in self._scan_directory(scan_dir, depth=0))
            stats[str(scan_dir)] = count
        return stats


def scan_device(config: ScannerConfig | None = None) -> Iterator[ScannedFile]:
    """
    Convenience function to scan all configured directories.
    
    Args:
        config: Optional scanner configuration. Uses default if not provided.
    
    Yields:
        ScannedFile objects for each indexable file found.
    """
    scanner = FileScanner(config)
    yield from scanner.scan_all()


def scan_for_new_files(config: ScannerConfig | None = None) -> Iterator[ScannedFile]:
    """
    Scan for new or modified files only.
    
    Args:
        config: Optional scanner configuration.
    
    Yields:
        ScannedFile objects for files needing (re)indexing.
    """
    scanner = FileScanner(config)
    yield from scanner.scan_for_changes()
