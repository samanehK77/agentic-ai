"""Chat sessions belong to the user who created them. Other users get 404, never a hint that the session exists."""
import pytest
from sqlalchemy import text


def create(test_client, patient_id="P-001", title="mine"):
    response = test_client.post("/api/sessions", json={"patient_id": patient_id, "title": title})
    assert response.status_code == 201
    return response.json()


def add_message(engine, session_id, content="hello"):
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO chat_messages (session_id, role, content) VALUES (:s, 'user', :c)"),
                           {"s": session_id, "c": content})


@pytest.fixture
def two_users(make_client, clean_chat):
    return make_client(), make_client()


def test_new_sessions_get_the_signed_in_user_as_owner(two_users):
    alice, _ = two_users
    created = create(alice)
    assert created["owner_id"] == str(alice.login["user_id"])


def test_each_user_lists_only_their_own_sessions(two_users):
    alice, bob = two_users
    mine = create(alice, title="alice session")
    create(bob, title="bob session")
    listed = alice.get("/api/sessions").json()
    assert listed["total"] == 1 and [item["session_id"] for item in listed["items"]] == [mine["session_id"]]
    assert [item["title"] for item in bob.get("/api/sessions").json()["items"]] == ["bob session"]


def test_patient_filter_stays_within_the_users_own_sessions(two_users):
    alice, bob = two_users
    create(alice, "P-001")
    create(bob, "P-001")
    assert alice.get("/api/sessions?patient_id=P-001").json()["total"] == 1


def test_another_users_session_is_404_not_found(two_users):
    alice, bob = two_users
    secret = create(alice)
    response = bob.get(f"/api/sessions/{secret['session_id']}")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
    assert alice.get(f"/api/sessions/{secret['session_id']}").status_code == 200


def test_another_users_session_looks_exactly_like_a_missing_one(two_users):
    alice, bob = two_users
    foreign = bob.get(f"/api/sessions/{create(alice)['session_id']}")
    missing = bob.get("/api/sessions/123e4567-e89b-42d3-a456-426614174000")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


def test_messages_of_another_users_session_are_not_readable(two_users, engine):
    alice, bob = two_users
    session = create(alice)
    add_message(engine, session["session_id"], "private words")
    response = bob.get(f"/api/sessions/{session['session_id']}/messages")
    assert response.status_code == 404 and "private words" not in response.text
    assert alice.get(f"/api/sessions/{session['session_id']}/messages").json()["total"] == 1


def test_legacy_sessions_without_an_owner_are_invisible_to_everyone(two_users, engine):
    alice, bob = two_users
    with engine.begin() as connection:
        legacy = connection.scalar(text(
            "INSERT INTO chat_sessions (patient_id, title) VALUES ('P-001', 'legacy session') RETURNING session_id"))
    add_message(engine, legacy, "old message")
    for user in (alice, bob):
        assert user.get("/api/sessions").json()["total"] == 0
        assert user.get(f"/api/sessions/{legacy}").status_code == 404
        assert user.get(f"/api/sessions/{legacy}/messages").status_code == 404
    with engine.connect() as connection:  # the row itself was not deleted by the migration or the API
        assert connection.scalar(text("SELECT count(*) FROM chat_sessions WHERE session_id = :s"), {"s": legacy}) == 1


def test_a_user_cannot_pass_an_owner_in_the_request(two_users):
    alice, bob = two_users
    response = alice.post("/api/sessions", json={"patient_id": "P-001", "owner_id": str(bob.login["user_id"])})
    assert response.status_code == 422
