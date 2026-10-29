"""POST /api/retrieval/search with a fake embedder: ordering, filters, errors, rate limit and privacy."""
import dataclasses
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import load_settings
from app.main import create_app
from app.retrieval.embedder import EmbedderProvider, RetrievalUnavailable
from app.retrieval.ratelimit import SlidingWindowLimiter
from tests.conftest import create_user_session, sign_in
from tests.fake_embedder import FINGERPRINT, FakeEmbedder, add_chunk, add_paper, unit

A, B = "test-ret-a", "test-ret-b"
SEARCH = "/api/retrieval/search"
HIT_KEYS = {"chunk_id", "paper_id", "title", "section_title", "section_type", "page_start", "page_end", "text",
            "similarity", "possible_injection"}


@pytest.fixture
def corpus(engine):
    """Two papers. For the query 'alpha' the cosine similarities are known: A1 1.0, A2 0.707, A3 0.316, B1 0.243, then ties at 0."""
    with engine.begin() as c:
        add_paper(c, A, "Paper A title")
        add_paper(c, B, "Paper B title")
        add_chunk(c, A, 1, unit(("alpha", 1)))
        add_chunk(c, A, 2, unit(("alpha", 1), ("beta", 1)))
        add_chunk(c, A, 3, unit(("alpha", 1), ("beta", 3)))
        add_chunk(c, A, 4, unit(("beta", 1)))
        add_chunk(c, B, 1, unit(("alpha", 1), ("gamma", 4)), injection=True)
        add_chunk(c, B, 2, unit(("gamma", 1)), kind="table_or_figure")
        # Never returned, even though several of them would rank first:
        add_chunk(c, A, 10, unit(("alpha", 1)), kind="references")        # an embedded references chunk (defence in depth)
        add_chunk(c, A, 11, unit(("alpha", 1)), kind="front_matter")
        add_chunk(c, A, 12, None, status="skipped")                       # skipped body chunk, no vector
        add_chunk(c, A, 13, None, status="pending")                       # not embedded yet
        add_chunk(c, A, 14, None, status="skipped", tokens=5)             # tiny chunk
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM papers WHERE paper_id IN (:a, :b)"), {"a": A, "b": B})


def make_client(engine, app):
    login = create_user_session(engine)
    client = TestClient(app, base_url="http://testserver.local")
    client.login = login
    return sign_in(client, login)


@pytest.fixture
def env(engine, corpus):
    embedder = FakeEmbedder()
    app = create_app(engine=engine, embedder=embedder)
    client = make_client(engine, app)
    client.embedder = embedder
    client.the_app = app
    with client:
        yield client
    with engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


def search(client, query="alpha", **extra):
    return client.post(SEARCH, json={"query": query, **extra})


def ids(response):
    return [hit["chunk_id"] for hit in response.json()["results"]]


# ---------------------------------------------------------------- results

def test_results_are_ordered_by_cosine_similarity(env):
    response = search(env, top_k=20)
    assert response.status_code == 200
    body = response.json()
    assert ids(response)[:4] == [f"{A}-c0001", f"{A}-c0002", f"{A}-c0003", f"{B}-c0001"]
    sims = [hit["similarity"] for hit in body["results"]]
    assert sims == sorted(sims, reverse=True)
    assert sims[:4] == pytest.approx([1.0, 0.7071, 0.3162, 0.2425], abs=1e-3)
    assert body["no_evidence"] is False and body["model"] == FINGERPRINT and body["top_k"] == 20


def test_response_shape_and_request_id(env):
    response = search(env, top_k=2)
    body = response.json()
    assert set(body) == {"request_id", "model", "top_k", "results", "no_evidence", "latency_ms"}
    assert body["request_id"] == response.headers["X-Request-ID"] and body["latency_ms"] >= 0
    first = body["results"][0]
    assert set(first) == HIT_KEYS
    assert first["title"] == "Paper A title" and first["text"] == f"Text of chunk {A}-c0001." and first["section_title"] == "A section"
    assert (first["page_start"], first["page_end"], first["section_type"], first["possible_injection"]) == (1, 1, "body", False)


def test_the_injection_marker_is_passed_through(env):
    hit = next(h for h in search(env, top_k=20).json()["results"] if h["chunk_id"] == f"{B}-c0001")
    assert hit["possible_injection"] is True


@pytest.mark.parametrize("k", [1, 2, 3, 5])
def test_top_k_limits_the_number_of_results(env, k):
    assert len(ids(search(env, top_k=k))) == k


def test_default_top_k_is_five(env):
    assert search(env).json()["top_k"] == 5 and len(ids(search(env))) == 5


def test_only_embedded_body_and_table_chunks_are_ever_returned(env):
    returned = set(ids(search(env, top_k=20)))
    assert returned == {f"{A}-c000{n}" for n in (1, 2, 3, 4)} | {f"{B}-c000{n}" for n in (1, 2)}
    for hidden in (10, 11, 12, 13, 14):
        assert f"{A}-c00{hidden}" not in returned


def test_the_paper_filter_applies_before_the_limit(env):
    """Paper B's chunks all rank below paper A's, yet asking for 2 results inside B still returns 2 from B."""
    response = search(env, top_k=2, paper_id=B)
    assert ids(response) == [f"{B}-c0001", f"{B}-c0002"]
    assert {h["paper_id"] for h in response.json()["results"]} == {B}


def test_a_filter_matching_nothing_returns_no_evidence_not_an_error(env, engine):
    with engine.begin() as c:
        add_paper(c, "test-ret-empty")
    try:
        body = search(env, paper_id="test-ret-empty").json()
        assert body["results"] == [] and body["no_evidence"] is True
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM papers WHERE paper_id = 'test-ret-empty'"))


def test_min_similarity_and_no_evidence(env):
    assert ids(search(env, min_similarity=0.5, top_k=20)) == [f"{A}-c0001", f"{A}-c0002"]
    assert ids(search(env, min_similarity=0.99, top_k=20)) == [f"{A}-c0001"]
    none = search(env, "gamma delta epsilon", min_similarity=0.9).json()
    assert none["results"] == [] and none["no_evidence"] is True


def test_an_unrelated_query_scores_near_zero(env):
    sims = [h["similarity"] for h in search(env, "completely unrelated words", top_k=20).json()["results"]]
    assert all(abs(s) < 1e-6 for s in sims)


def test_default_threshold_comes_from_the_settings_and_can_be_overridden(engine, corpus):
    settings = dataclasses.replace(load_settings(), retrieval_min_similarity=0.5)
    app = create_app(engine=engine, settings=settings, embedder=FakeEmbedder())
    client = make_client(engine, app)
    try:
        with client:
            assert ids(search(client, top_k=20)) == [f"{A}-c0001", f"{A}-c0002"]
            assert len(ids(search(client, top_k=20, min_similarity=0))) == 6
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


def test_the_model_is_loaded_once(engine, corpus):
    loads = []

    def factory():
        loads.append(1)
        return FakeEmbedder()

    app = create_app(engine=engine, embedder=FakeEmbedder())
    app.state.embedder_provider = EmbedderProvider(factory)
    client = make_client(engine, app)
    try:
        with client:
            for _ in range(3):
                assert search(client).status_code == 200
        assert len(loads) == 1
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


# ---------------------------------------------------------------- validation and access

@pytest.mark.parametrize("body", [
    {"query": "alpha", "top_k": 0}, {"query": "alpha", "top_k": 21}, {"query": "alpha", "top_k": -3},
    {"query": ""}, {"query": "    "}, {"query": "x" * 1001}, {}, {"query": 5},
    {"query": "alpha", "min_similarity": 1.5}, {"query": "alpha", "min_similarity": -0.1},
    {"query": "alpha", "paper_id": "Bad_Id"}, {"query": "alpha", "unexpected": True},
])
def test_invalid_requests_are_422(env, body):
    response = env.post(SEARCH, json=body)
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


def test_out_of_range_top_k_is_rejected_not_clamped(env):
    assert env.post(SEARCH, json={"query": "alpha", "top_k": 500}).status_code == 422


def test_a_query_of_exactly_1000_characters_is_accepted(env):
    assert search(env, "a" * 1000).status_code == 200


def test_the_query_is_trimmed(env):
    search(env, "   alpha   ")
    assert env.embedder.calls[-1] == ["alpha"]


def test_unknown_paper_is_404(env):
    response = search(env, paper_id="no-such-paper")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


def test_anonymous_gets_401(env, engine):
    with TestClient(env.the_app, base_url="http://testserver.local") as anon:
        response = anon.post(SEARCH, json={"query": "alpha"})
    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


def test_missing_or_wrong_csrf_header_is_403(env):
    del env.headers["X-CSRF-Token"]
    response = env.post(SEARCH, json={"query": "alpha"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_failed"
    assert env.post(SEARCH, json={"query": "alpha"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403


def test_errors_use_the_standard_format_with_request_ids(env):
    response = env.post(SEARCH, json={"query": ""})
    error = response.json()["error"]
    assert set(error) >= {"code", "message", "request_id"} and error["request_id"] == response.headers["X-Request-ID"]


# ---------------------------------------------------------------- index problems

def test_not_ready_when_nothing_is_embedded(engine):
    app = create_app(engine=engine, embedder=FakeEmbedder())
    client = make_client(engine, app)
    try:
        with client:
            response = search(client)
        assert response.status_code == 503 and response.json()["error"]["code"] == "retrieval_not_ready"
        assert "python -m app.embedding" in response.json()["error"]["message"]
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


def test_index_incompatible_when_a_chunk_has_another_fingerprint(env, engine):
    with engine.begin() as c:
        add_chunk(c, A, 20, unit(("alpha", 1)), fingerprint="other-model@x|dim=384|l2norm")
    response = search(env)
    assert response.status_code == 503 and response.json()["error"]["code"] == "index_incompatible"


def test_unavailable_when_the_embedding_dependency_is_missing(engine, corpus):
    def broken():
        raise RetrievalUnavailable("sentence-transformers (and torch) are not installed.")

    app = create_app(engine=engine, embedder=FakeEmbedder())
    app.state.embedder_provider = EmbedderProvider(broken)
    client = make_client(engine, app)
    try:
        with client:
            response = search(client)
        assert response.status_code == 503 and response.json()["error"]["code"] == "retrieval_unavailable"
        assert "not installed" in response.json()["error"]["message"]
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


def test_the_app_starts_and_other_routes_work_without_the_embedding_dependency(engine):
    app = create_app(engine=engine)  # the default provider would try to load the real model, lazily
    client = make_client(engine, app)
    try:
        with client:
            assert client.get("/api/patients").status_code == 200
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


def test_a_model_returning_a_bad_vector_is_a_503(engine, corpus):
    class Broken(FakeEmbedder):
        def embed(self, texts):
            return [[0.5] * 10 for _ in texts]

    app = create_app(engine=engine, embedder=Broken())
    client = make_client(engine, app)
    try:
        with client:
            assert search(client).status_code == 503
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


# ---------------------------------------------------------------- rate limit

def test_rate_limit_returns_429_with_retry_after(engine, corpus):
    settings = dataclasses.replace(load_settings(), retrieval_rate_limit_per_minute=3)
    app = create_app(engine=engine, settings=settings, embedder=FakeEmbedder())
    client = make_client(engine, app)
    try:
        with client:
            assert [search(client).status_code for _ in range(3)] == [200, 200, 200]
            response = search(client)
        assert response.status_code == 429
        error = response.json()["error"]
        assert error["code"] == "rate_limited" and error["request_id"] == response.headers["X-Request-ID"]
        assert 1 <= int(response.headers["Retry-After"]) <= 60
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


def test_rate_limit_is_per_user_and_invalid_requests_do_not_count(engine, corpus):
    settings = dataclasses.replace(load_settings(), retrieval_rate_limit_per_minute=2)
    app = create_app(engine=engine, settings=settings, embedder=FakeEmbedder())
    first, second = make_client(engine, app), make_client(engine, app)
    try:
        with first, second:
            for _ in range(3):
                assert first.post(SEARCH, json={"query": ""}).status_code == 422  # not counted
            assert [search(first).status_code for _ in range(3)] == [200, 200, 429]
            assert search(second).status_code == 200
    finally:
        with engine.begin() as c:
            for client in (first, second):
                c.execute(text("DELETE FROM users WHERE id = :u"), {"u": client.login["user_id"]})


def test_sliding_window_limiter_forgets_old_hits():
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 60, clock=lambda: now[0])
    assert limiter.check("u") is None and limiter.check("u") is None
    assert limiter.check("u") == 60
    now[0] = 61
    assert limiter.check("u") is None


# ---------------------------------------------------------------- privacy

def test_responses_contain_no_file_names_paths_or_hashes(env):
    dump = search(env, top_k=20).text.lower()
    for forbidden in ("secret-file", ".pdf", "file_name", "content_sha256", "data/papers", "c:\\\\", "text_sha256"):
        assert forbidden not in dump, forbidden


def test_the_query_text_is_never_logged(env, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "CONFIDENTIAL-QUERY-TEXT alpha"
    assert search(env, secret).status_code == 200
    env.post(SEARCH, json={"query": secret, "top_k": 99})  # a rejected request too
    ours = [r for r in caplog.records if r.name.startswith("mindevidence")]
    assert any("search request=" in r.getMessage() for r in ours)
    for record in ours:
        assert "CONFIDENTIAL" not in record.getMessage() and "CONFIDENTIAL" not in str(record.args)
    line = next(r.getMessage() for r in ours if "search request=" in r.getMessage())
    assert "user=" in line and "top_k=" in line and "results=" in line and "latency_ms=" in line
