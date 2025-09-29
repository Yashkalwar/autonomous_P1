"""Utility helpers for managing user-provided documents."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple


class DocumentManager:
    """Handle storage, listing, and text extraction for user documents."""

    SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".json"}

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # Public API -----------------------------------------------------------------
    def list_documents(self) -> List[Path]:
        """Return the available files in the managed directory."""
        return sorted([p for p in self.base_dir.iterdir() if p.is_file()])

    def load_text_from_reference(self, reference: str) -> Tuple[bool, Optional[str], Optional[str], Optional[Path]]:
        """Load text from a managed document or an explicit path."""
        reference = reference.strip().strip('"')
        if not reference:
            return False, None, "No file reference provided.", None

        candidate = Path(reference).expanduser()
        if candidate.is_file() and self._is_supported(candidate):
            success, text, error = self._read_text(candidate)
            return success, text, error, candidate if success else None

        managed_candidate = (self.base_dir / reference).resolve()
        if self._is_within_base(managed_candidate) and managed_candidate.is_file():
            if not self._is_supported(managed_candidate):
                return False, None, f"Unsupported file type: {managed_candidate.suffix or 'unknown'}", None
            success, text, error = self._read_text(managed_candidate)
            return success, text, error, managed_candidate if success else None

        # Attempt case-insensitive lookup inside the managed directory
        lower_reference = reference.lower()
        for doc in self.list_documents():
            if doc.name.lower() == lower_reference:
                success, text, error = self._read_text(doc)
                return success, text, error, doc if success else None

        return False, None, f"Document not found: {reference}", None

    def parse_summary_input(self, raw_input: str) -> Tuple[bool, Optional[str], Optional[str], Optional[Path]]:
        """Interpret user-provided summary input, supporting file: prefixes."""
        stripped = raw_input.strip()
        lowered = stripped.lower()

        if lowered.startswith("file:"):
            reference = stripped[5:].strip()
            return self.load_text_from_reference(reference)

        if lowered.startswith("file "):
            reference = stripped[5:].strip()
            return self.load_text_from_reference(reference)

        direct_candidate = self.base_dir / stripped
        if self._is_within_base(direct_candidate) and direct_candidate.is_file():
            return self.load_text_from_reference(stripped)

        return True, stripped, None, None

    def load_latest_document_text(self) -> Tuple[bool, Optional[str], Optional[str], Optional[Path]]:
        """Load text from the most recently updated document if available."""
        documents = self.list_documents()
        supported_documents = [doc for doc in documents if self._is_supported(doc)]

        if not supported_documents:
            return False, None, "No supported documents found in the shared folder.", None

        latest = None
        latest_mtime = None
        for doc in supported_documents:
            try:
                mtime = doc.stat().st_mtime
            except OSError:
                continue
            if latest is None or (latest_mtime is not None and mtime > latest_mtime) or latest_mtime is None:
                latest = doc
                latest_mtime = mtime

        if not latest:
            return False, None, "Unable to read documents in the shared folder.", None

        success, text, error = self._read_text(latest)
        if success:
            return True, text, None, latest
        return False, None, error or f"Unable to extract text from {latest.name}", latest

    # Internal helpers -----------------------------------------------------------
    def _is_supported(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def _is_within_base(self, path: Path) -> bool:
        try:
            path.relative_to(self.base_dir)
            return True
        except ValueError:
            return False

    def _read_text(self, path: Path) -> Tuple[bool, Optional[str], Optional[str]]:
        suffix = path.suffix.lower()

        if suffix in {".txt", ".md", ".json"}:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:  # pragma: no cover - filesystem dependent
                return False, None, str(exc)
            text = text.strip()
            if not text:
                return False, None, f"No readable text found in {path.name}"
            return True, text, None

        if suffix == ".pdf":
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except ImportError:
                return False, None, "PyPDF2 is required to read PDF files."

            try:
                reader = PdfReader(str(path))
            except Exception as exc:  # pragma: no cover - depends on file
                return False, None, str(exc)

            pages = []
            for page in reader.pages:
                try:
                    text = page.extract_text() or ""
                except Exception:  # pragma: no cover - depends on file
                    text = ""
                if text.strip():
                    pages.append(text.strip())

            combined = "\n\n".join(pages).strip()
            if not combined:
                return False, None, f"Unable to extract text from {path.name}"
            return True, combined, None

        if suffix == ".docx":
            try:
                from docx import Document  # type: ignore
            except ImportError:
                return False, None, "python-docx is required to read DOCX files."

            try:
                document = Document(str(path))
            except Exception as exc:  # pragma: no cover - depends on file
                return False, None, str(exc)

            paragraphs = [para.text.strip() for para in document.paragraphs if para.text.strip()]
            combined = "\n\n".join(paragraphs).strip()
            if not combined:
                return False, None, f"No readable content found in {path.name}"
            return True, combined, None

        return False, None, f"Unsupported file type: {suffix or 'unknown'}"
