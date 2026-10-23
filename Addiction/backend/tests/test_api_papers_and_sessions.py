import json
import re
from uuid import UUID

import pytest
from sqlalchemy import text

PAPER_IDS = [
    "nida-principles-of-drug-addiction-treatment",
    "psychosocial-interventions-for-alcohol-use-disorder-review",
    "who-mhgap-guideline-2023",
    "who-mhgap-intervention-guide-v2",
]


# ---------------------------------------------------------------- papers

def test_papers_are_the_seeded_four(client):
    body = client.get("/api/papers").json()
    assert [p["paper_id"] for p in body["items"]] == PAPER_IDS
    assert body["total"] == 4
    assert all(p["ingest_status"] == "not_ingested" for p in body["items"])
    assert all(re.fullmatch(r"unknown|\d{4}", p["publication_year"]) for p in body["items"])
    by_id = {p["paper_id"]: p for p in body["items"]}
    assert by_id["who-mhgap-guideline-2023"]["publication_year"] == "2023"
    assert by_id["psychosocial-interventions-for-alcohol-use-disorder-review"]["publisher"] == "unknown"


def test_papers_expose_no_file_paths_or_text(client):
    response = client.get("/api/papers")
    dump = response.text.lower()
    for forbidden in (".pdf", "data/papers", "data\\\\papers", "c:\\\\", "/users/", "file_path", "\"path\""):
        assert forbidden not in dump, forbidden
    assert set(response.json()["items"][0]) == {
        "paper_id", "title", "document_type", "publisher", "publication_year", "source_note", "ingest_status", "created_at"}


def test_papers_pagination(client):
    body = client.get("/api/papers?limit=2&offset=3").json()
    assert [p["paper_id"] for p in body["items"]] == PAPER_IDS[3:]
    assert client.get("/api/papers?limit=101").status_code == 422


# ---------------------------------------------------------------- sessions

def create(client, **body):
    return client.post("/api/sessions", json=body)


def test_create_session(client, clean_chat):
    response = create(client, patient_id="P-001", title="  My first questions  ")
    assert response.status_code == 201
    body = response.json()
    assert UUID(body["session_id"])
    assert body["patient_id"] == "P-001"
    assert body["title"] == "My first questions"  # whitespace trimmed
    assert body["owner_id"] is None
    assert response.headers["Location"].endswith(f"/api/sessions/{body['session_id']}")
    fetched = client.get(response.headers["Location"])
    assert fetched.status_code == 200 and fetched.json() == body


def test_default_title(client, clean_chat):
    body = create(client, patient_id="P-007").json()
    assert body["title"] == "Conversation about P-007"


def test_unknown_patient_is_404(client, clean_chat):
    response = create(client, patient_id="P-999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("body", [
    {},
    {"patient_id": "ABC"},
    {"patient_id": "P-001", "title": ""},
    {"patient_id": "P-001", "title": "   "},
    {"patient_id": "P-001", "title": "x" * 121},
    {"patient_id": "P-001", "title": 5},
    {"patient_id": "P-001", "owner_id": "123e4567-e89b-42d3-a456-426614174000"},  # extra fields are rejected
    {"patient_id": None},
])
def test_invalid_session_bodies_are_422(client, clean_chat, body):
    assert create(client, **body).status_code == 422


def test_a_120_character_title_is_accepted(client, clean_chat):
    assert create(client, patient_id="P-001", title="x" * 120).status_code == 201


def test_malformed_json_is_422(client):
    response = client.post("/api/sessions", content="{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_list_sessions_filter_and_pagination(client, clean_chat):
    first = create(client, patient_id="P-001", title="one").json()
    second = create(client, patient_id="P-002", title="two").json()
    third = create(client, patient_id="P-001", title="three").json()

    everything = client.get("/api/sessions").json()
    assert everything["total"] == 3
    assert [s["session_id"] for s in everything["items"]] == [third["session_id"], second["session_id"], first["session_id"]]

    only_p1 = client.get("/api/sessions?patient_id=P-001").json()
    assert only_p1["total"] == 2
    assert {s["patient_id"] for s in only_p1["items"]} == {"P-001"}

    page = client.get("/api/sessions?limit=1&offset=1").json()
    assert [s["session_id"] for s in page["items"]] == [second["session_id"]]
    assert client.get("/api/sessions?patient_id=ABC").status_code == 422


def test_messages_of_a_new_session_are_an_empty_list(client, clean_chat):
    session = create(client, patient_id="P-003").json()
    response = client.get(f"/api/sessions/{session['session_id']}/messages")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_messages_are_ordered_by_created_at(client, engine, clean_chat):
    session_id = create(client, patient_id="P-003").json()["session_id"]
    rows = [  # inserted out of order on purpose
        ("assistant", "rag", "second", "2026-01-01 10:00:02+00"),
        ("user", None, "first", "2026-01-01 10:00:01+00"),
        ("assistant", "both", "third", "2026-01-01 10:00:03+00"),
    ]
    with engine.begin() as connection:
        for role, mode, content, created in rows:
            connection.execute(text(
                "INSERT INTO chat_messages (session_id, role, mode, content, created_at) "
                "VALUES (:s, :r, :m, :c, :t)"), {"s": session_id, "r": role, "m": mode, "c": content, "t": created})

    body = client.get(f"/api/sessions/{session_id}/messages").json()
    assert [m["content"] for m in body["items"]] == ["first", "second", "third"]
    assert body["total"] == 3
    assert body["items"][0]["mode"] is None and body["items"][1]["mode"] == "rag"
    page = client.get(f"/api/sessions/{session_id}/messages?limit=1&offset=2").json()
    assert [m["content"] for m in page["items"]] == ["third"]


def test_unknown_session_is_404_and_malformed_is_422(client):
    unknown = "123e4567-e89b-42d3-a456-426614174000"
    assert client.get(f"/api/sessions/{unknown}").status_code == 404
    assert client.get(f"/api/sessions/{unknown}/messages").status_code == 404
    assert client.get("/api/sessions/not-a-uuid/messages").status_code == 422
    assert client.get("/api/sessions/not-a-uuid").status_code == 422


def test_creating_sessions_never_changes_patient_data(client, engine, clean_chat):
    with engine.connect() as connection:
        before = connection.scalar(text("SELECT count(*) FROM patients"))
    create(client, patient_id="P-001")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM patients")) == before == 10


def test_session_responses_are_json(client, clean_chat):
    response = create(client, patient_id="P-001")
    json.loads(response.text)
    assert response.headers["content-type"].startswith("application/json")
