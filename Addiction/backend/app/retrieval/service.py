"""Search rules between the router and the repository: index checks, query embedding, no-evidence flag."""
import math

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.repositories import retrieval as repo
from app.retrieval.embedder import DIMENSION, EmbedderProvider, RetrievalUnavailable


def unavailable(reason: str) -> ApiError:
    return ApiError(503, "retrieval_unavailable", reason)


def search(db: Session, provider: EmbedderProvider, *, query: str, top_k: int, paper_id: str | None,
           min_similarity: float | None) -> dict:
    try:
        embedder = provider.get()
    except RetrievalUnavailable as error:
        raise unavailable(str(error)) from None

    embedded, fingerprints = repo.index_state(db)
    if embedded == 0:
        raise ApiError(503, "retrieval_not_ready",
                       "No chunks have been embedded yet. Run: python -m app.embedding")
    if fingerprints != [embedder.fingerprint]:
        raise ApiError(503, "index_incompatible",
                       "The stored embeddings were made by a different model or settings. "
                       "Re-embed with: python -m app.embedding --force")

    vector = embedder.embed([query])[0]
    norm = math.sqrt(sum(x * x for x in vector))
    if len(vector) != DIMENSION or abs(norm - 1.0) > 1e-3:
        raise unavailable("The embedding model returned an unexpected vector.")

    rows = repo.search(db, vector, top_k, paper_id, min_similarity)
    for row in rows:
        row["similarity"] = round(float(row["similarity"]), 4)
    return {"model": embedder.fingerprint, "results": rows, "no_evidence": len(rows) == 0}
