"""Administrator-only ingestion endpoints: access control, data shape, pagination, filters and no leaks."""
import pytest
from sqlalchemy import text

PAPER = "test-adm-paper"
SECRET_FILE = "secret-internal-file-name.pdf"
SECRET_SHA = "a" * 64
ADMIN_ROUTES = [
    "/api/admin/papers", f"/api/admin/papers/{PAPER}", f"/api/admin/papers/{PAPER}/chunks", f"/api/admin/chunks/{PAPER}-c0001",
]


@pytest.fixture
def seeded(engine):
    """One ingested test paper with five chunks (two references, one flagged)."""
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO papers (paper_id, title, document_type, publisher, publication_year, source_note, file_name, "
            "content_sha256, page_count, chunking_version, ingested_at, ingest_status, low_text_pages, metadata_source) "
            "VALUES (:p, 'Admin test paper', 'review', 'unknown', 'unknown', 'synthetic', :f, :h, 20, 'p1|test', now(), "
            "'ingested', '{3,7}', 'document_text')"), {"p": PAPER, "f": SECRET_FILE, "h": SECRET_SHA})
        kinds = ["front_matter", "body", "body", "references", "references"]
        for ordinal, kind in enumerate(kinds, start=1):
            connection.execute(text(
                "INSERT INTO paper_chunks (chunk_id, paper_id, ordinal, text, token_count, page_start, page_end, "
                "section_title, section_type, text_sha256, possible_injection) "
                "VALUES (:id, :p, :o, :t, 12, :ps, :ps, :title, :k, :h, :inj)"),
                {"id": f"{PAPER}-c{ordinal:04d}", "p": PAPER, "o": ordinal, "t": f"Chunk number {ordinal} text of the test paper.",
                 "ps": ordinal, "title": None if ordinal == 1 else "A section", "k": kind, "h": "b" * 64, "inj": ordinal == 3})
    yield
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM papers WHERE paper_id = :p"), {"p": PAPER})


# ---------------------------------------------------------------- access control

@pytest.mark.parametrize("path", ADMIN_ROUTES)
def test_anonymous_gets_401(anon_client, seeded, path):
    response = anon_client.get(path)
    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("path", ADMIN_ROUTES)
def test_students_get_403(make_client, seeded, path):
    response = make_client("student").get(path)
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "forbidden" and error["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("path", ADMIN_ROUTES)
def test_admins_get_200(make_client, seeded, path):
    assert make_client("admin").get(path).status_code == 200


def test_no_endpoint_can_start_an_ingestion(make_client, seeded):
    admin = make_client("admin")
    for method in ("post", "put", "patch", "delete"):
        for path in ("/api/admin/papers", f"/api/admin/papers/{PAPER}", "/api/admin/ingest", "/api/admin/ingestion"):
            assert getattr(admin, method)(path).status_code in (404, 405)


def test_the_student_papers_endpoint_is_unchanged_and_has_no_ingestion_fields(client):
    item = client.get("/api/papers").json()["items"][0]
    assert set(item) == {"paper_id", "title", "document_type", "publisher", "publication_year", "source_note",
                         "ingest_status", "created_at"}


# ---------------------------------------------------------------- data

def test_admin_paper_list_and_detail(make_client, seeded):
    admin = make_client("admin")
    listing = admin.get("/api/admin/papers").json()
    item = next(p for p in listing["items"] if p["paper_id"] == PAPER)
    assert item["ingest_status"] == "ingested" and item["page_count"] == 20 and item["chunk_count"] == 5
    assert item["low_text_page_count"] == 2 and item["chunking_version"] == "p1|test"
    assert item["metadata_source"] == "document_text" and item["ingested_at"] and "doi" in item
    detail = admin.get(f"/api/admin/papers/{PAPER}").json()
    assert detail["low_text_pages"] == [3, 7]
    assert detail["chunks_by_section_type"] == {"front_matter": 1, "body": 2, "references": 2}
    assert listing["total"] >= 6  # the five registered papers plus this one


def test_seeded_but_not_ingested_papers_show_zero_chunks(make_client):
    item = next(p for p in make_client("admin").get("/api/admin/papers").json()["items"]
                if p["paper_id"] == "who-mhgap-guideline-2023")
    assert item["ingest_status"] == "not_ingested" and item["chunk_count"] == 0 and item["page_count"] is None


def test_chunks_are_listed_in_order_with_full_text(make_client, seeded):
    body = make_client("admin").get(f"/api/admin/papers/{PAPER}/chunks").json()
    assert body["total"] == 5 and [c["ordinal"] for c in body["items"]] == [1, 2, 3, 4, 5]
    first = body["items"][0]
    assert set(first) == {"chunk_id", "paper_id", "ordinal", "text", "token_count", "page_start", "page_end",
                          "section_title", "section_type", "possible_injection", "created_at"}
    assert first["text"] == "Chunk number 1 text of the test paper." and first["section_title"] is None
    assert body["items"][2]["possible_injection"] is True


def test_chunk_pagination_and_section_filter(make_client, seeded):
    admin = make_client("admin")
    page = admin.get(f"/api/admin/papers/{PAPER}/chunks?limit=2&offset=3").json()
    assert [c["ordinal"] for c in page["items"]] == [4, 5] and page["total"] == 5 and page["limit"] == 2
    refs = admin.get(f"/api/admin/papers/{PAPER}/chunks?section_type=references").json()
    assert refs["total"] == 2 and {c["section_type"] for c in refs["items"]} == {"references"}
    assert admin.get(f"/api/admin/papers/{PAPER}/chunks?section_type=body&limit=1").json()["total"] == 2


def test_single_chunk(make_client, seeded):
    chunk = make_client("admin").get(f"/api/admin/chunks/{PAPER}-c0002").json()
    assert chunk["chunk_id"] == f"{PAPER}-c0002" and chunk["paper_id"] == PAPER and chunk["section_type"] == "body"


# ---------------------------------------------------------------- errors

@pytest.mark.parametrize("path", [
    "/api/admin/papers/no-such-paper", "/api/admin/papers/no-such-paper/chunks", "/api/admin/chunks/no-such-paper-c0001",
    f"/api/admin/chunks/{PAPER}-c9999",
])
def test_unknown_ids_are_404_in_the_standard_format(make_client, seeded, path):
    response = make_client("admin").get(path)
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found" and error["request_id"]


@pytest.mark.parametrize("path", [
    "/api/admin/papers/Bad_Id", "/api/admin/papers/-x", "/api/admin/chunks/not-a-chunk", "/api/admin/chunks/x-c12",
    f"/api/admin/papers/{PAPER}/chunks?section_type=novel", f"/api/admin/papers/{PAPER}/chunks?limit=101",
    f"/api/admin/papers/{PAPER}/chunks?offset=-1", "/api/admin/papers?limit=0",
])
def test_malformed_input_is_422_in_the_standard_format(make_client, seeded, path):
    response = make_client("admin").get(path)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------- no leaks

@pytest.mark.parametrize("path", ADMIN_ROUTES[:3])
def test_responses_never_contain_file_names_paths_or_hashes(make_client, seeded, path):
    response = make_client("admin").get(path)
    dump = response.text.lower()
    for forbidden in (SECRET_FILE, SECRET_SHA, "file_name", "content_sha256", "data/papers", "data\\\\papers", "c:\\\\", ".pdf"):
        assert forbidden.lower() not in dump, forbidden


def test_real_registered_file_names_do_not_appear_in_any_admin_response(make_client):
    admin = make_client("admin")
    dump = admin.get("/api/admin/papers").text + admin.get("/api/admin/papers/who-mhgap-guideline-2023").text
    assert ".pdf" not in dump.lower()


def test_openapi_lists_the_admin_routes_with_403(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/admin/papers", "/api/admin/papers/{paper_id}", "/api/admin/papers/{paper_id}/chunks", "/api/admin/chunks/{chunk_id}"):
        assert {"200", "401", "403"} <= set(paths[path]["get"]["responses"]), path
