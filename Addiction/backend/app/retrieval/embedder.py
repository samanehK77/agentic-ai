"""The embedding model behind a small interface.

sentence-transformers and torch are imported lazily and only here, so the API and the test suite start without
them. If they (or the model files) are missing, `RetrievalUnavailable` is raised and the API answers 503.
Everything runs on the CPU and offline: the model files must already be in backend/models/.
"""
import hashlib
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.ingestion.config import BACKEND_DIR, TOKENIZER_NAME, TOKENIZER_REVISION

logger = logging.getLogger("mindevidence.retrieval")

MODEL_NAME = TOKENIZER_NAME
MODEL_REVISION = TOKENIZER_REVISION  # the same pinned revision Batch 05 used for token counting, never "latest"
DIMENSION = 384
WEIGHTS_FILE = "model.safetensors"
WEIGHTS_SHA256 = "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db"  # of that revision
DEFAULT_MODEL_DIR = BACKEND_DIR / "models" / "all-MiniLM-L6-v2"
INSTALL_HINT = ("Install the embedding requirements and download the model as described in docs/RETRIEVAL.md "
                "(pip install -r requirements-embeddings.txt).")


def fingerprint() -> str:
    """Identifies the exact model, revision, dimension and normalization that produced a vector."""
    return f"{MODEL_NAME}@{MODEL_REVISION}|dim={DIMENSION}|l2norm"


class RetrievalUnavailable(Exception):
    """The embedding model cannot be used on this machine. The message is short and safe to show."""


class Embedder(Protocol):
    fingerprint: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """L2-normalized vectors, one per text."""
        ...


class SentenceTransformerEmbedder:
    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR):
        weights = model_dir / WEIGHTS_FILE
        if not weights.is_file():
            raise RetrievalUnavailable(f"The embedding model files were not found. {INSTALL_HINT}")
        digest = hashlib.sha256()
        with weights.open("rb") as handle:
            for piece in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(piece)
        if digest.hexdigest() != WEIGHTS_SHA256:
            raise RetrievalUnavailable(
                "The model weights do not match the pinned revision; download them again as described in docs/RETRIEVAL.md.")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # never reach out to the network
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RetrievalUnavailable(f"sentence-transformers (and torch) are not installed. {INSTALL_HINT}") from None
        try:
            self._model = SentenceTransformer(str(model_dir), device="cpu")
        except Exception as error:
            logger.warning("model load failed: %s", type(error).__name__)
            raise RetrievalUnavailable("The embedding model could not be loaded.") from None
        self.fingerprint = fingerprint()

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False,
                                     batch_size=32)
        return vectors.tolist()


def load_embedder(model_dir: Path | None = None) -> Embedder:
    return SentenceTransformerEmbedder(model_dir or Path(os.environ.get("EMBEDDING_MODEL_PATH", "").strip() or DEFAULT_MODEL_DIR))


class EmbedderProvider:
    """Loads the model once, on first use (a thread-safe lazy singleton). A failed load is not cached,
    so installing the missing pieces fixes a running server after the next request."""

    def __init__(self, factory: Callable[[], Embedder] = load_embedder):
        self._factory = factory
        self._embedder: Embedder | None = None
        self._lock = threading.Lock()

    def get(self) -> Embedder:
        if self._embedder is None:
            with self._lock:
                if self._embedder is None:
                    self._embedder = self._factory()
        return self._embedder

    @property
    def fingerprint(self) -> str:
        """The fingerprint of the loaded embedder, or the pinned real one if nothing is loaded yet (no model load)."""
        return self._embedder.fingerprint if self._embedder is not None else fingerprint()

    @classmethod
    def fixed(cls, embedder: Embedder) -> "EmbedderProvider":
        provider = cls(lambda: embedder)
        provider._embedder = embedder
        return provider
