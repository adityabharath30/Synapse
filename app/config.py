from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DOCS_DIR = ROOT_DIR / "docs"

# Alias for compatibility with watcher.py
DOCS_PATH = DOCS_DIR

INDEX_PATH = DATA_DIR / "index"
RESEARCH_PATH = DATA_DIR / "research"

# Scanner configuration
SCANNER_CONFIG_PATH = ROOT_DIR / "scanner_config.yaml"
SCAN_MANIFEST_PATH = DATA_DIR / "scan_manifest.json"


def ensure_data_dir() -> None:
    """Ensure the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
