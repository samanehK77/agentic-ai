"""Optional sanity check on the real PDFs. Skipped when the PDFs or the tokenizer file are not on this machine.

It checks only that every document is ingested or explained, and that chunks respect the token limit. It says nothing
about retrieval quality (that is measured in Batch 06). Nothing from the documents is printed.
"""
import pytest

from app.ingestion.config import IngestConfig
from app.ingestion.pipeline import process_pdf
from app.ingestion.registry import UnsafePathError, load_registry, resolve_pdf
from app.ingestion.tokens import MiniLMTokenCounter

CONFIG = IngestConfig()


def _available():
    if not CONFIG.tokenizer_path.is_file():
        return []
    found = []
    for entry in load_registry():
        try:
            found.append((entry, resolve_pdf(CONFIG.papers_dir, entry.file_name)))
        except UnsafePathError:
            continue
    return found


AVAILABLE = _available()


@pytest.mark.skipif(not AVAILABLE, reason="real PDFs or tokenizer.json not present on this machine")
@pytest.mark.parametrize("entry,path", AVAILABLE, ids=[e.paper_id for e, _ in AVAILABLE])
def test_real_documents_are_ingested_or_explained(entry, path):
    counter = MiniLMTokenCounter(CONFIG.tokenizer_path)
    result = process_pdf(path, entry.paper_id, CONFIG, counter)
    assert result.status in ("ingested", "needs_ocr", "failed")
    if result.status == "ingested":
        assert result.chunks
        assert all(0 < c.token_count <= CONFIG.chunk_max for c in result.chunks)
        assert all(c.text.strip() for c in result.chunks)
        assert result.page_count > 0
    else:
        assert result.reason  # never silent
