"""
Synapse Startup Module.

Handles initialization tasks:
- Auto-migrate JSON manifest to SQLite
- Ensure required directories exist
- Validate configuration
- Check for updates
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file early so API keys are available
load_dotenv()

logger = logging.getLogger("rag")


def ensure_directories() -> None:
    """Ensure required directories exist."""
    from app.config import DATA_DIR, DOCS_DIR
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.debug("Data directory: %s", DATA_DIR)
    logger.debug("Docs directory: %s", DOCS_DIR)


def migrate_manifest_if_needed() -> bool:
    """
    Migrate JSON manifest to SQLite if needed.
    
    Returns:
        True if migration was performed or already done
    """
    from app.config import DATA_DIR, SCAN_MANIFEST_PATH
    
    json_path = SCAN_MANIFEST_PATH  # data/scan_manifest.json
    db_path = DATA_DIR / "manifest.db"
    
    # If SQLite already exists, no migration needed
    if db_path.exists():
        logger.debug("SQLite manifest already exists")
        return True
    
    # If JSON doesn't exist, no migration needed
    if not json_path.exists():
        logger.debug("No JSON manifest to migrate")
        # Create fresh SQLite manifest
        from app.manifest_db import SQLiteManifest
        SQLiteManifest(db_path)
        return True
    
    # Perform migration
    logger.info("Migrating JSON manifest to SQLite...")
    
    try:
        from app.manifest_db import migrate_json_to_sqlite
        success = migrate_json_to_sqlite(json_path, db_path)
        
        if success:
            logger.info("Migration completed successfully")
        else:
            logger.warning("Migration had issues")
        
        return success
        
    except Exception as e:
        logger.error("Migration failed: %s", e)
        return False


def validate_config() -> list[str]:
    """
    Validate configuration and return list of warnings.
    
    Returns:
        List of warning messages (empty if all OK)
    """
    warnings = []
    
    try:
        from app.scanner_config import get_config
        config = get_config()
        
        # Check scan directories
        if not config.scan_directories:
            warnings.append("No scan directories configured. Add directories in scanner_config.yaml")
        else:
            for dir_path in config.scan_directories:
                if not dir_path.exists():
                    warnings.append(f"Scan directory does not exist: {dir_path}")
        
        # Check API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            try:
                from app.security import get_key_manager
                from app.config import DATA_DIR
                km = get_key_manager(DATA_DIR)
                api_key = km.get_api_key("OPENAI_API_KEY")
            except Exception:
                pass
        
        if not api_key:
            warnings.append("OpenAI API key not configured. Some features will be limited.")
        
    except Exception as e:
        warnings.append(f"Config validation error: {e}")
    
    return warnings


def check_index_exists() -> bool:
    """Check if the search index exists."""
    from app.config import INDEX_PATH
    
    faiss_path = INDEX_PATH.with_suffix(".faiss")
    return faiss_path.exists()


def initialize() -> dict:
    """
    Run all startup tasks.
    
    Returns:
        Dict with status information:
        - success: bool
        - warnings: list[str]
        - index_exists: bool
        - migration_done: bool
    """
    result = {
        "success": True,
        "warnings": [],
        "index_exists": False,
        "migration_done": False,
    }
    
    try:
        # Ensure directories
        ensure_directories()
        
        # Migrate manifest
        result["migration_done"] = migrate_manifest_if_needed()
        
        # Validate config
        result["warnings"] = validate_config()
        
        # Check index
        result["index_exists"] = check_index_exists()
        
        if not result["index_exists"]:
            result["warnings"].append(
                "Search index not found. Run 'python scripts/watcher.py --scan-now' to build it."
            )
        
    except Exception as e:
        logger.error("Startup initialization failed: %s", e)
        result["success"] = False
        result["warnings"].append(f"Initialization error: {e}")
    
    return result


def print_startup_info() -> None:
    """Print startup information to console."""
    info = initialize()
    
    print("=" * 50)
    print("Synapse - Startup Check")
    print("=" * 50)
    
    if info["success"]:
        print("✅ Initialization successful")
    else:
        print("❌ Initialization had errors")
    
    if info["migration_done"]:
        print("✅ Database ready")
    
    if info["index_exists"]:
        print("✅ Search index found")
    else:
        print("⚠️  Search index not found")
    
    if info["warnings"]:
        print("\nWarnings:")
        for warning in info["warnings"]:
            print(f"  ⚠️  {warning}")
    
    print("=" * 50)


# Auto-run initialization when module is imported
# (but only if not being imported for testing)
if os.getenv("RAG_SKIP_INIT") != "1":
    _init_result = initialize()
    if _init_result["warnings"]:
        for w in _init_result["warnings"]:
            logger.warning(w)
