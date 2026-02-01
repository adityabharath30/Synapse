# Sample Documents Folder

This folder is for testing the RAG system with sample documents.

## Supported File Types

- **Text**: `.txt`, `.md`
- **Documents**: `.pdf`, `.docx`
- **Spreadsheets**: `.csv`, `.xlsx`
- **Images**: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.bmp`, `.tiff`

## Usage

1. Place sample documents in this folder
2. Run `python scripts/index_builder.py` to index them
3. Use the Synapse UI to search

## Device-Wide Scanning

For scanning your entire Mac, configure `scanner_config.yaml` instead:

```yaml
scan_directories:
  - ~/Documents
  - ~/Desktop
```

Then run: `python scripts/watcher.py --scan-now`

## Note

Personal documents should NOT be committed to git. Add them to `.gitignore`.
