# Personal Spotlight Search

A local, Spotlight-style semantic search system for your personal documents. Ask questions in natural language and get precise, extractive answers powered by GPT-4o-mini.

![Spotlight Demo](docs/demo.png)

## Features

- 🔍 **Semantic Search** — Find documents by meaning, not just keywords
- 🤖 **GPT-Powered Extraction** — Get precise answers, not document dumps
- ⚡ **Instant Results** — Sub-second search with cached embeddings
- ⌨️ **Keyboard-First** — Spotlight-style UX with global hotkey
- 📁 **Auto-Indexing** — Watch folder for new documents
- 🔒 **100% Local** — Your data never leaves your machine (except GPT calls)

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add your OpenAI API key to .env
echo "OPENAI_API_KEY=sk-your-key-here" > .env

# 3. Add documents to /docs folder
cp ~/Documents/*.pdf docs/

# 4. Build the index
python scripts/index_builder.py

# 5. Launch Spotlight
python ui/spotlight_ui.py
```

## Usage

### Search UI

```bash
python ui/spotlight_ui.py
```

- **Type to search** — Results appear instantly as you type
- **↑/↓** — Navigate results
- **Enter** — Open selected document
- **Esc** — Close window

### Global Hotkey Launcher

```bash
python scripts/launcher.py
```

Runs in background and listens for:
- **⌘+Shift+Space** (macOS)
- **Ctrl+Shift+Space** (Windows/Linux)

### Auto-Indexing Watcher

```bash
python scripts/watcher.py
```

Watches `/docs` folder and automatically indexes new or modified files.

### Manual Indexing

```bash
python scripts/index_builder.py
```

Rebuilds the entire index from scratch.

## Project Structure

```
RAG/
├── app/                    # Core package
│   ├── config.py           # Paths and settings
│   ├── ingestion.py        # Document extraction (PDF, DOCX, TXT)
│   ├── chunker.py          # Sentence-aware text chunking
│   ├── embeddings.py       # SentenceTransformer embeddings (cached)
│   ├── vector_store.py     # FAISS vector index
│   ├── query_intent.py     # Intent classification
│   ├── llm.py              # OpenAI GPT integration
│   ├── rag_answerer.py     # Extractive QA pipeline
│   ├── search_service.py   # Search orchestration
│   └── research_store.py   # Research memory index
│
├── ui/
│   └── spotlight_ui.py     # Modern Spotlight UI
│
├── scripts/
│   ├── index_builder.py    # Build FAISS index
│   ├── launcher.py         # Global hotkey launcher
│   └── watcher.py          # Auto-indexing watcher
│
├── docs/                   # Your documents go here
├── data/                   # Generated indexes (auto-created)
├── .env                    # API keys (create this)
└── requirements.txt
```

## Configuration

### Environment Variables (.env)

```bash
# Required for GPT extraction
OPENAI_API_KEY=sk-your-key-here

# Optional: Change embedding model
EMBEDDING_MODEL=multi-qa-MiniLM-L6-cos-v1
```

### Supported File Types

- PDF (`.pdf`)
- Word Documents (`.docx`)
- Text Files (`.txt`, `.md`)
- Spreadsheets (`.csv`, `.xlsx`)

## How It Works

### 1. Indexing Pipeline

```
Documents → Text Extraction → Chunking → Embeddings → FAISS Index
```

- Documents are split into ~200-word chunks with sentence boundaries preserved
- Each chunk is embedded using SentenceTransformers
- Embeddings are stored in a FAISS index for fast similarity search

### 2. Query Pipeline

```
Query → Embed → FAISS Search → Top Chunks → GPT Extraction → Answer
```

1. **Retrieval** — Query is embedded and matched against the index
2. **Extraction** — GPT-4o-mini extracts the smallest answer span from each chunk
3. **Selection** — Best answer is selected based on confidence and relevance
4. **Compression** — Long answers are compressed to ≤25 words

### 3. Research Memory

Past queries and answers are stored in a separate FAISS index, enabling:
- "What did I search for last week?"
- Building on previous research

## Performance

| Metric | Value |
|--------|-------|
| Index Build | ~10 docs/sec |
| Search Latency | <500ms |
| GPT Extraction | ~300ms/chunk |
| Model Load | ~2s (first time, then cached) |

## Troubleshooting

### "No module named 'app'"

Run from the project root:
```bash
cd /path/to/RAG
python scripts/index_builder.py
```

### "OPENAI_API_KEY not found"

Create `.env` file:
```bash
echo "OPENAI_API_KEY=sk-your-key" > .env
```

### "No documents found"

Add documents to the `/docs` folder:
```bash
mkdir -p docs
cp ~/Documents/*.pdf docs/
```

### Slow first search

The embedding model loads on first use (~2s). Use the launcher for pre-loading:
```bash
python scripts/launcher.py
```

## Development

### Install Dev Dependencies

```bash
pip install -r requirements.txt
pip install customtkinter pynput watchdog
```

### Run Tests

```bash
python -m pytest tests/
```

### Code Style

```bash
ruff check app/ scripts/ ui/
```

## License

MIT License — Use freely for personal projects.

## Credits

Built with:
- [SentenceTransformers](https://www.sbert.net/) — Local embeddings
- [FAISS](https://github.com/facebookresearch/faiss) — Vector search
- [OpenAI](https://openai.com/) — GPT extraction
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) — Modern UI
