from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from docx import Document
from PyPDF2 import PdfReader


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".csv", ".xlsx"}


@dataclass(frozen=True)
class IngestedDocument:
    filename: str
    filepath: str
    content: str


class DocumentIngester:
    def __init__(self, docs_dir: Path) -> None:
        self.docs_dir = docs_dir

    def ingest_all(self) -> list[dict[str, str]]:
        if not self.docs_dir.exists():
            raise RuntimeError(
                f"Docs directory not found: {self.docs_dir}. "
                "Create it and add files before indexing."
            )

        files = [
            path
            for path in self.docs_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if not files:
            raise RuntimeError(
                f"No supported documents found in {self.docs_dir}. "
                f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        documents: list[IngestedDocument] = []
        for path in files:
            content = self._read_file(path)
            if content.strip():
                documents.append(
                    IngestedDocument(
                        filename=path.name,
                        filepath=str(path),
                        content=content,
                    )
                )

        if not documents:
            raise RuntimeError("All documents were empty after ingestion.")

        return [
            {
                "filename": doc.filename,
                "filepath": doc.filepath,
                "content": doc.content,
            }
            for doc in documents
        ]

    def _read_file(self, path: Path) -> str:
        suffix = path.suffix.lower()
        try:
            if suffix in {".txt", ".md"}:
                return path.read_text(encoding="utf-8", errors="ignore")
            if suffix == ".pdf":
                reader = PdfReader(str(path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            if suffix == ".docx":
                doc = Document(str(path))
                return "\n".join(p.text for p in doc.paragraphs)
            if suffix == ".csv":
                df = pd.read_csv(path)
                return df.to_csv(index=False)
            if suffix == ".xlsx":
                df = pd.read_excel(path)
                return df.to_csv(index=False)
        except Exception as exc:
            raise RuntimeError(f"Failed to read {path}") from exc

        raise RuntimeError(f"Unsupported file type: {path}")
