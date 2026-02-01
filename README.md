# Synapse

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

There's moments where you want to find you credit card number quick, or the dates for your hotel bookings but don't want to dig through files. There's moments where you might even forget where you stored all that information. For that: there's Synapse. **Spotlight indexes _files_, Synapse indexes _context_**.
It's a local semantic search system for your personal documents. Ask questions in natural language and get precise, extractive answers.

## Features

- 🔍 **Semantic Search** — Find documents by meaning, not just keywords
- 🤖 **GPT-Powered Extraction** — Get precise answers, not document dumps
- ⚡ **Instant Results** — Sub-second search with cached embeddings
- ⌨️ **Keyboard-First** — Global hotkey (⌘+Shift+Space) for instant access
- 📁 **Device-Wide Scanning** — Index documents across your entire Mac
- 🔒 **Privacy-First** — Encrypted storage, audit logging, local embeddings
- 🖼️ **Image Support** — Extract text and descriptions from images via Vision API
- 🗑️ **Data Control** — Export or delete all your data with one command

## Technical Highlights

| Component | Technology | Purpose |
|-----------|------------|---------|
| Vector Search | FAISS IndexFlatIP | Sub-millisecond similarity search |
| Embeddings | SentenceTransformers | Local, privacy-preserving embeddings |
| Extractive QA | GPT-4o-mini | 4-stage extraction pipeline |
| Storage | SQLite + Encrypted Pickle | Fast queries, secure at rest |
| UI | CustomTkinter | Native-feeling dark mode UI |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER INTERFACE                                     │
│  synapse_ui.py                      launcher.py (⌘+Shift+Space)             │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SEARCH SERVICE                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ Query Embed │ →  │ FAISS Search│ →  │ GPT Extract │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
│         │                  │                  │                              │
│         │         Hybrid Scoring:     4-Stage Pipeline:                      │
│         │         • Semantic sim      • Per-chunk extraction                 │
│         │         • Keyword overlap   • Candidate selection                  │
│         │         • Length bonus      • Answer compression                   │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA LAYER                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ FAISS Index │    │ SQLite Meta │    │ Research Mem│                      │
│  │ (vectors)   │    │ (file info) │    │ (past Q&A)  │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INGESTION PIPELINE                                 │
│  scanner.py → ingestion.py → chunker.py → embeddings.py → vector_store.py  │
│      │                                                                       │
│      │  Parallel processing │ Sentence-aware │ Local embeddings             │
│      │  Security filtering  │ ~200 words/chunk│ 384 dimensions              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/adityabharath30/Synapse.git
cd Synapse
pip install -r requirements.txt

# 2. Add your OpenAI API key
echo "OPENAI_API_KEY=sk-your-key-here" > .env

# 3. Configure directories to scan (edit scanner_config.yaml)
# By default, scans ~/Documents and ~/Desktop

# 4. Build the index
python scripts/watcher.py --scan-now

# 5. Launch Synapse UI
python ui/synapse_ui.py
```

## Usage

### Search UI

```bash
python ui/synapse_ui.py
```

| Key | Action |
|-----|--------|
| Type | Search as you type |
| ↑/↓ | Navigate results |
| Enter | Open document |
| Esc | Close |

### Device-Wide Scanning

```bash
# One-time full scan
python scripts/watcher.py --scan-now

# Real-time watcher (runs in background)
python scripts/watcher.py

# Check indexing stats
python scripts/watcher.py --stats
```

### Privacy Controls

```bash
# List all indexed files
python -m app.privacy --list

# Export all your data
python -m app.privacy --export ~/my-data-export

# Delete everything
python -m app.privacy --delete-all
```

## Configuration

### scanner_config.yaml

```yaml
# Directories to scan (explicit opt-in)
scan_directories:
  - ~/Documents
  - ~/Desktop

# Security: never index these
excluded_file_patterns:
  - "*.env"
  - "*password*"
  - "*credentials*"

# Image processing (disabled by default - uses OpenAI Vision)
process_images: false

# Performance
parallel_workers: 4

# Privacy
local_only_mode: false  # Set true to disable all cloud APIs
enable_audit_logging: true
```

### Supported File Types

| Type | Extensions | Extraction Method |
|------|------------|-------------------|
| Documents | `.pdf`, `.docx` | PyPDF2, python-docx |
| Text | `.txt`, `.md` | Direct read |
| Spreadsheets | `.csv`, `.xlsx` | Pandas |
| Images | `.jpg`, `.png`, `.gif` | OpenAI Vision API |

## Security & Privacy

| Feature | Description |
|---------|-------------|
| **Local Embeddings** | SentenceTransformers runs 100% locally |
| **Encrypted Storage** | AES-128 encryption for index (optional) |
| **Keychain Integration** | API keys stored in macOS Keychain |
| **Audit Logging** | Every file access is logged |
| **Data Export** | Export everything you've indexed |
| **Data Deletion** | One-command complete data wipe |

## Performance

| Metric | Value |
|--------|-------|
| Index Build | ~10 docs/sec (parallel) |
| Search Latency | <500ms |
| GPT Extraction | ~300ms/chunk |
| Model Load | ~2s (then cached) |
| Memory Usage | ~500MB (with model) |

## Development

### Run Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html
```

### Code Quality

```bash
# Lint
ruff check app/ scripts/ tests/

# Security scan
bandit -r app/ -ll
```

## Project Structure

```
RAG/
├── app/                     # Core package
│   ├── ingestion.py         # Document extraction (parallel)
│   ├── chunker.py           # Sentence-aware chunking
│   ├── embeddings.py        # SentenceTransformer (cached)
│   ├── vector_store.py      # FAISS wrapper
│   ├── rag_answerer.py      # 4-stage extraction pipeline
│   ├── search_service.py    # Search orchestration
│   ├── scanner.py           # Device-wide file discovery
│   ├── scanner_config.py    # Configuration management
│   ├── security.py          # Encryption, keychain, audit
│   └── privacy.py           # Data export/deletion CLI
│
├── ui/
│   └── synapse_ui.py        # CustomTkinter Synapse UI
│
├── scripts/
│   ├── watcher.py           # Device scanner + real-time watcher
│   ├── index_builder.py     # Manual index rebuild
│   └── launcher.py          # Global hotkey launcher
│
├── tests/                   # Pytest test suite
├── scanner_config.yaml      # User configuration
└── requirements.txt
```

## Troubleshooting

### "No module named 'app'"

Run from project root:
```bash
cd /path/to/Synapse
python scripts/watcher.py
```

### "OPENAI_API_KEY not found"

Either create `.env` file or use keychain:
```python
from app.security import get_key_manager
km = get_key_manager(DATA_DIR)
km.set_api_key("OPENAI_API_KEY", "sk-your-key")
```

### Scanning is slow

Check `scanner_config.yaml`:
- Reduce `scan_directories`
- Increase `parallel_workers`
- Disable `process_images` (uses Vision API)

## License

MIT License — Use freely for personal and commercial projects.

## Acknowledgments

Built with:
- [SentenceTransformers](https://www.sbert.net/) — Local embeddings
- [FAISS](https://github.com/facebookresearch/faiss) — Vector search
- [OpenAI](https://openai.com/) — GPT extraction
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) — Modern UI
