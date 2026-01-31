"""
Privacy Controls for RAG System.

Provides:
- Complete data deletion ("forget everything")
- Data export for transparency
- Indexed files listing
- Privacy-preserving statistics
"""
from __future__ import annotations

import csv
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, INDEX_PATH, ensure_data_dir
from app.security import get_audit_logger

logger = logging.getLogger("rag.privacy")


class PrivacyManager:
    """
    Manages user privacy controls for the RAG system.
    
    Features:
    - View what files are indexed
    - Export all indexed data
    - Delete all indexed data
    - Clear audit logs
    """
    
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or DATA_DIR
        self.audit = get_audit_logger(self.data_dir)
    
    # ========================================================================
    # Data Visibility
    # ========================================================================
    
    def list_indexed_files(self) -> list[dict]:
        """
        List all files currently in the index.
        
        Returns list of dicts with: filepath, filename, indexed_at, chunk_count
        """
        manifest_path = self.data_dir / "scan_manifest.json"
        
        if not manifest_path.exists():
            return []
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            files = []
            for filepath, info in data.get("files", {}).items():
                files.append({
                    "filepath": filepath,
                    "filename": Path(filepath).name,
                    "indexed_at": info.get("indexed_at", "unknown"),
                    "chunk_count": info.get("chunk_count", 0),
                    "size_bytes": info.get("size", 0),
                })
            
            # Sort by indexed_at descending
            files.sort(key=lambda x: x["indexed_at"], reverse=True)
            return files
        
        except Exception as e:
            logger.error("Failed to list indexed files: %s", e)
            return []
    
    def get_indexed_file_count(self) -> int:
        """Get count of indexed files."""
        return len(self.list_indexed_files())
    
    def get_storage_stats(self) -> dict:
        """
        Get statistics about stored data.
        
        Returns dict with:
        - total_files: Number of indexed files
        - total_chunks: Number of text chunks
        - index_size_mb: Size of FAISS index
        - manifest_size_kb: Size of manifest
        - audit_log_entries: Number of audit entries
        """
        stats = {
            "total_files": 0,
            "total_chunks": 0,
            "index_size_mb": 0.0,
            "manifest_size_kb": 0.0,
            "audit_log_entries": 0,
            "total_storage_mb": 0.0,
        }
        
        # Count files and chunks from manifest
        manifest_path = self.data_dir / "scan_manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                files = data.get("files", {})
                stats["total_files"] = len(files)
                stats["total_chunks"] = sum(
                    f.get("chunk_count", 0) for f in files.values()
                )
                stats["manifest_size_kb"] = manifest_path.stat().st_size / 1024
            except Exception:
                pass
        
        # Get index size
        faiss_path = Path(str(INDEX_PATH) + ".faiss")
        pkl_path = Path(str(INDEX_PATH) + ".pkl")
        
        if faiss_path.exists():
            stats["index_size_mb"] += faiss_path.stat().st_size / (1024 * 1024)
        if pkl_path.exists():
            stats["index_size_mb"] += pkl_path.stat().st_size / (1024 * 1024)
        
        # Round index size
        stats["index_size_mb"] = round(stats["index_size_mb"], 2)
        
        # Get audit log stats
        audit_stats = self.audit.get_stats()
        stats["audit_log_entries"] = audit_stats.get("total_entries", 0)
        
        # Calculate total storage
        total_bytes = 0
        for path in self.data_dir.rglob("*"):
            if path.is_file():
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    pass
        stats["total_storage_mb"] = round(total_bytes / (1024 * 1024), 2)
        
        return stats
    
    # ========================================================================
    # Data Export
    # ========================================================================
    
    def export_manifest(self, output_path: Path) -> bool:
        """
        Export the file manifest as human-readable JSON.
        
        Shows exactly what files have been indexed.
        """
        manifest_path = self.data_dir / "scan_manifest.json"
        
        if not manifest_path.exists():
            logger.warning("No manifest to export")
            return False
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Make it human-readable
            export_data = {
                "export_date": datetime.now().isoformat(),
                "description": "List of all files indexed by RAG Personal Search",
                "total_files": len(data.get("files", {})),
                "last_full_scan": data.get("last_full_scan"),
                "files": []
            }
            
            for filepath, info in data.get("files", {}).items():
                export_data["files"].append({
                    "path": filepath,
                    "name": Path(filepath).name,
                    "indexed_at": info.get("indexed_at"),
                    "chunks_created": info.get("chunk_count"),
                    "file_size_bytes": info.get("size"),
                })
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            
            self.audit.log_data_export("manifest", str(output_path))
            logger.info("Exported manifest to %s", output_path)
            return True
        
        except Exception as e:
            logger.error("Failed to export manifest: %s", e)
            return False
    
    def export_indexed_files_csv(self, output_path: Path) -> bool:
        """
        Export list of indexed files as CSV.
        
        Columns: filepath, filename, indexed_at, chunk_count, size_bytes
        """
        files = self.list_indexed_files()
        
        if not files:
            logger.warning("No files to export")
            return False
        
        try:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "filepath", "filename", "indexed_at", "chunk_count", "size_bytes"
                ])
                writer.writeheader()
                writer.writerows(files)
            
            self.audit.log_data_export("files_csv", str(output_path))
            logger.info("Exported %d files to %s", len(files), output_path)
            return True
        
        except Exception as e:
            logger.error("Failed to export CSV: %s", e)
            return False
    
    def export_audit_log(self, output_path: Path) -> bool:
        """
        Export audit log for transparency.
        """
        audit_path = self.data_dir / "audit.log"
        
        if not audit_path.exists():
            logger.warning("No audit log to export")
            return False
        
        try:
            shutil.copy(audit_path, output_path)
            self.audit.log_data_export("audit_log", str(output_path))
            logger.info("Exported audit log to %s", output_path)
            return True
        
        except Exception as e:
            logger.error("Failed to export audit log: %s", e)
            return False
    
    def export_all(self, output_dir: Path) -> dict[str, bool]:
        """
        Export all user data to a directory.
        
        Creates:
        - manifest.json: List of indexed files
        - files.csv: Indexed files as CSV
        - audit.log: Audit trail
        - stats.json: Storage statistics
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        results = {
            "manifest": self.export_manifest(output_dir / "manifest.json"),
            "files_csv": self.export_indexed_files_csv(output_dir / "files.csv"),
            "audit_log": self.export_audit_log(output_dir / "audit.log"),
        }
        
        # Export stats
        try:
            stats = self.get_storage_stats()
            stats["export_date"] = datetime.now().isoformat()
            with open(output_dir / "stats.json", "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2)
            results["stats"] = True
        except Exception:
            results["stats"] = False
        
        return results
    
    # ========================================================================
    # Data Deletion
    # ========================================================================
    
    def delete_file_from_index(self, filepath: str) -> bool:
        """
        Remove a specific file from the manifest.
        
        Note: Vectors remain in FAISS until full rebuild.
        """
        manifest_path = self.data_dir / "scan_manifest.json"
        
        if not manifest_path.exists():
            return False
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if filepath in data.get("files", {}):
                del data["files"][filepath]
                
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                
                self.audit.log_file_deleted(filepath)
                logger.info("Removed from index: %s", filepath)
                return True
            
            return False
        
        except Exception as e:
            logger.error("Failed to delete file from index: %s", e)
            return False
    
    def delete_index(self) -> bool:
        """
        Delete the FAISS index and metadata.
        
        Keeps the manifest (list of files) but removes all vectors.
        """
        try:
            faiss_path = Path(str(INDEX_PATH) + ".faiss")
            pkl_path = Path(str(INDEX_PATH) + ".pkl")
            
            deleted = False
            
            if faiss_path.exists():
                faiss_path.unlink()
                deleted = True
            
            if pkl_path.exists():
                pkl_path.unlink()
                deleted = True
            
            if deleted:
                self.audit.log_data_deletion("index")
                logger.info("Deleted index files")
            
            return deleted
        
        except Exception as e:
            logger.error("Failed to delete index: %s", e)
            return False
    
    def delete_manifest(self) -> bool:
        """Delete the file manifest."""
        manifest_path = self.data_dir / "scan_manifest.json"
        
        try:
            if manifest_path.exists():
                manifest_path.unlink()
                self.audit.log_data_deletion("manifest")
                logger.info("Deleted manifest")
                return True
            return False
        
        except Exception as e:
            logger.error("Failed to delete manifest: %s", e)
            return False
    
    def delete_audit_log(self) -> bool:
        """Delete the audit log."""
        audit_path = self.data_dir / "audit.log"
        
        try:
            if audit_path.exists():
                audit_path.unlink()
                logger.info("Deleted audit log")
                return True
            return False
        
        except Exception as e:
            logger.error("Failed to delete audit log: %s", e)
            return False
    
    def delete_all_data(self, confirm: bool = False) -> bool:
        """
        Delete ALL indexed data - "forget everything".
        
        This is irreversible! Requires confirm=True.
        
        Deletes:
        - FAISS index
        - Metadata pickle
        - File manifest
        - Audit log
        - Encryption keys/salt
        """
        if not confirm:
            logger.error("delete_all_data requires confirm=True")
            return False
        
        try:
            # Log before we delete the log
            self.audit.log_data_deletion("ALL_DATA")
            
            deleted_items = []
            
            # Delete index files
            for suffix in [".faiss", ".pkl"]:
                path = Path(str(INDEX_PATH) + suffix)
                if path.exists():
                    path.unlink()
                    deleted_items.append(path.name)
            
            # Delete manifest
            manifest_path = self.data_dir / "scan_manifest.json"
            if manifest_path.exists():
                manifest_path.unlink()
                deleted_items.append("scan_manifest.json")
            
            # Delete index manifest (old format)
            old_manifest = self.data_dir / "index_manifest.json"
            if old_manifest.exists():
                old_manifest.unlink()
                deleted_items.append("index_manifest.json")
            
            # Delete audit log
            audit_path = self.data_dir / "audit.log"
            if audit_path.exists():
                audit_path.unlink()
                deleted_items.append("audit.log")
            
            # Delete encryption salt
            salt_path = self.data_dir / ".salt"
            if salt_path.exists():
                salt_path.unlink()
                deleted_items.append(".salt")
            
            # Delete scanner logs
            for log_file in ["scanner.log", "scanner_error.log"]:
                log_path = self.data_dir / log_file
                if log_path.exists():
                    log_path.unlink()
                    deleted_items.append(log_file)
            
            logger.info("Deleted all data: %s", ", ".join(deleted_items))
            print(f"✅ Deleted {len(deleted_items)} items: {', '.join(deleted_items)}")
            return True
        
        except Exception as e:
            logger.error("Failed to delete all data: %s", e)
            return False
    
    # ========================================================================
    # Privacy Report
    # ========================================================================
    
    def generate_privacy_report(self) -> dict:
        """
        Generate a privacy report for the user.
        
        Shows:
        - What data is stored
        - Where it's stored
        - How to delete it
        """
        stats = self.get_storage_stats()
        files = self.list_indexed_files()
        
        # Get unique directories being indexed
        directories = set()
        for f in files:
            directories.add(str(Path(f["filepath"]).parent))
        
        return {
            "report_date": datetime.now().isoformat(),
            "summary": {
                "files_indexed": stats["total_files"],
                "text_chunks_stored": stats["total_chunks"],
                "storage_used_mb": stats["total_storage_mb"],
            },
            "data_locations": {
                "index_directory": str(self.data_dir),
                "faiss_index": str(INDEX_PATH) + ".faiss",
                "metadata": str(INDEX_PATH) + ".pkl",
                "manifest": str(self.data_dir / "scan_manifest.json"),
                "audit_log": str(self.data_dir / "audit.log"),
            },
            "source_directories": sorted(directories)[:20],  # Top 20
            "recent_files": [f["filepath"] for f in files[:10]],
            "how_to_delete": {
                "single_file": "privacy.delete_file_from_index(filepath)",
                "all_vectors": "privacy.delete_index()",
                "everything": "privacy.delete_all_data(confirm=True)",
            },
            "cloud_services_used": {
                "openai_vision": "Used for image processing (if enabled)",
                "openai_embeddings": "NOT used (local sentence-transformers)",
            },
        }


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """CLI interface for privacy controls."""
    import argparse
    
    parser = argparse.ArgumentParser(description="RAG Privacy Controls")
    parser.add_argument("--list", action="store_true", help="List indexed files")
    parser.add_argument("--stats", action="store_true", help="Show storage stats")
    parser.add_argument("--export", type=str, help="Export all data to directory")
    parser.add_argument("--delete-index", action="store_true", help="Delete index only")
    parser.add_argument("--delete-all", action="store_true", help="Delete ALL data")
    parser.add_argument("--report", action="store_true", help="Generate privacy report")
    
    args = parser.parse_args()
    
    ensure_data_dir()
    privacy = PrivacyManager()
    
    if args.list:
        files = privacy.list_indexed_files()
        print(f"\n📁 Indexed Files ({len(files)} total):\n")
        for f in files[:50]:  # Show first 50
            print(f"  • {f['filename']} ({f['chunk_count']} chunks)")
        if len(files) > 50:
            print(f"  ... and {len(files) - 50} more")
    
    elif args.stats:
        stats = privacy.get_storage_stats()
        print("\n📊 Storage Statistics:\n")
        print(f"  Files indexed:     {stats['total_files']}")
        print(f"  Text chunks:       {stats['total_chunks']}")
        print(f"  Index size:        {stats['index_size_mb']} MB")
        print(f"  Total storage:     {stats['total_storage_mb']} MB")
        print(f"  Audit log entries: {stats['audit_log_entries']}")
    
    elif args.export:
        output_dir = Path(args.export)
        results = privacy.export_all(output_dir)
        print(f"\n📤 Exported to {output_dir}:")
        for item, success in results.items():
            status = "✅" if success else "❌"
            print(f"  {status} {item}")
    
    elif args.delete_index:
        confirm = input("Delete index? This cannot be undone. Type 'yes' to confirm: ")
        if confirm.lower() == "yes":
            privacy.delete_index()
            print("✅ Index deleted")
        else:
            print("Cancelled")
    
    elif args.delete_all:
        print("\n⚠️  WARNING: This will delete ALL indexed data!")
        print("This action cannot be undone.\n")
        confirm = input("Type 'DELETE ALL' to confirm: ")
        if confirm == "DELETE ALL":
            privacy.delete_all_data(confirm=True)
        else:
            print("Cancelled")
    
    elif args.report:
        report = privacy.generate_privacy_report()
        print("\n🔒 Privacy Report:\n")
        print(json.dumps(report, indent=2))
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
