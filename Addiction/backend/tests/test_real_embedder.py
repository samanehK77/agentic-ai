"""Optional test with the real model. Skipped automatically when torch, sentence-transformers or the model files are missing."""
import importlib.util
import math

import pytest

from app.retrieval.embedder import DEFAULT_MODEL_DIR, DIMENSION, WEIGHTS_FILE, RetrievalUnavailable, load_embedder

AVAILABLE = (importlib.util.find_spec("sentence_transformers") is not None and (DEFAULT_MODEL_DIR / WEIGHTS_FILE).is_file())
pytestmark = pytest.mark.skipif(not AVAILABLE, reason="sentence-transformers, torch or the model files are not available")


@pytest.fixture(scope="module")
def embedder():
    try:
        return load_embedder()
    except RetrievalUnavailable as error:  # for example weights that do not match the pinned revision
        pytest.skip(str(error))


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_vectors_have_384_dimensions_and_unit_norm(embedder):
    vectors = embedder.embed(["Naltrexone reduces heavy drinking.", "Motivational interviewing builds motivation."])
    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == DIMENSION == 384
        assert math.sqrt(sum(x * x for x in vector)) == pytest.approx(1.0, abs=1e-3)


def test_a_paraphrase_is_closer_than_an_unrelated_sentence(embedder):
    base, paraphrase, unrelated = embedder.embed([
        "Medication can help people with alcohol use disorder to drink less.",
        "Drugs are able to assist patients who have an alcohol problem to reduce their drinking.",
        "The football match ended in a draw after extra time.",
    ])
    assert cosine(base, paraphrase) > cosine(base, unrelated)


def test_the_fingerprint_names_the_pinned_revision(embedder):
    from app.ingestion.config import TOKENIZER_REVISION

    assert embedder.fingerprint.endswith(f"@{TOKENIZER_REVISION}|dim=384|l2norm")
