"""A deterministic stand-in for the embedding model, so retrieval tests need neither torch nor the network.

Vectors are built by hand from a few named axes, so the nearest-neighbour order of every test is known in advance.
"""
import math

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text

DIMENSION = 384
FINGERPRINT = "fake-model@test|dim=384|l2norm"
AXES = {"alpha": 0, "beta": 1, "gamma": 2, "delta": 3, "epsilon": 4}
UNRELATED_AXIS = 100


def unit(*weights: tuple[str, float]) -> list[float]:
    """An L2-normalized 384-dimensional vector from (axis name, weight) pairs."""
    vector = [0.0] * DIMENSION
    for name, weight in weights:
        vector[AXES[name]] = weight
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


class FakeEmbedder:
    """Maps the axis words found in a text (alpha, beta, ...) to a unit vector; any other text is 'unrelated'."""

    fingerprint = FINGERPRINT

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors = []
        for value in texts:
            words = [w for w in value.lower().split() if w in AXES]
            if words:
                vectors.append(unit(*[(w, 1.0) for w in words]))
            else:
                vector = [0.0] * DIMENSION
                vector[UNRELATED_AXIS] = 1.0
                vectors.append(vector)
        return vectors


_INSERT_CHUNK = text("""
    INSERT INTO paper_chunks (chunk_id, paper_id, ordinal, text, token_count, page_start, page_end, section_title,
                              section_type, text_sha256, possible_injection, embedding, embedding_fingerprint,
                              embedding_status, embedded_at)
    VALUES (:id, :paper, :ordinal, :text, :tokens, :page, :page, :title, :kind, :sha, :injection,
            CAST(:vector AS vector), :fp, :status, CASE WHEN :status = 'embedded' THEN now() END)""").bindparams(
    bindparam("vector", type_=Vector(384)))


def add_paper(connection, paper_id: str, title: str | None = None) -> None:
    connection.execute(text(
        "INSERT INTO papers (paper_id, title, document_type, publisher, publication_year, source_note, file_name) "
        "VALUES (:p, :t, 'review', 'unknown', 'unknown', 'synthetic test document', :f)"),
        {"p": paper_id, "t": title or f"Title of {paper_id}", "f": f"{paper_id}-secret-file.pdf"})


def add_chunk(connection, paper_id: str, ordinal: int, vector: list[float] | None, *, kind: str = "body", tokens: int = 100,
              status: str = "embedded", fingerprint: str | None = FINGERPRINT, injection: bool = False,
              title: str | None = "A section", body: str | None = None) -> str:
    chunk_id = f"{paper_id}-c{ordinal:04d}"
    if status != "embedded":
        vector, fingerprint = None, None
    connection.execute(_INSERT_CHUNK, {
        "id": chunk_id, "paper": paper_id, "ordinal": ordinal, "text": body or f"Text of chunk {chunk_id}.",
        "tokens": tokens, "page": ordinal, "title": title, "kind": kind, "sha": "d" * 64, "injection": injection,
        "vector": vector, "fp": fingerprint, "status": status})
    return chunk_id
