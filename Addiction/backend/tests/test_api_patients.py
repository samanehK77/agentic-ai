import pytest
from sqlalchemy import text

from db.config import QUERIES_DIR
from tests.test_seed_data import PATIENT_IDS


def all_history(client, patient_id):
    response = client.get(f"/api/patients/{patient_id}/history?limit=100")
    assert response.status_code == 200
    return response.json()


def test_list_returns_exactly_the_ten_seeded_patients(client):
    body = client.get("/api/patients").json()
    assert [p["patient_id"] for p in body["items"]] == PATIENT_IDS
    assert (body["total"], body["limit"], body["offset"]) == (10, 50, 0)
    assert all(p["is_synthetic"] is True for p in body["items"])
    assert all(p["primary_use_subject"] for p in body["items"])


def test_pagination(client):
    body = client.get("/api/patients?limit=3&offset=2").json()
    assert [p["patient_id"] for p in body["items"]] == ["P-003", "P-004", "P-005"]
    assert (body["total"], body["limit"], body["offset"]) == (10, 3, 2)
    assert client.get("/api/patients?offset=10").json()["items"] == []
    assert len(client.get("/api/patients?limit=100").json()["items"]) == 10


@pytest.mark.parametrize("query", ["limit=101", "limit=0", "limit=-1", "limit=abc", "offset=-1"])
def test_pagination_limits_are_enforced(client, query):
    assert client.get(f"/api/patients?{query}").status_code == 422


def test_category_filter(client):
    body = client.get("/api/patients?category=alcohol").json()
    assert [p["patient_id"] for p in body["items"]] == ["P-001", "P-002"]
    assert body["total"] == 2
    behavioral = client.get("/api/patients?category=behavioral&limit=1").json()
    assert behavioral["total"] == 2 and len(behavioral["items"]) == 1
    assert client.get("/api/patients?category=chocolate").status_code == 422


@pytest.mark.parametrize("patient_id", PATIENT_IDS)
def test_profile_matches_the_database(client, conn, patient_id):
    body = client.get(f"/api/patients/{patient_id}").json()
    assert body["is_synthetic"] is True

    patient = conn.execute(text("SELECT * FROM patients WHERE patient_id = :p"), {"p": patient_id}).mappings().one()
    for column in ("age_at_intake", "gender", "primary_category", "living_situation", "employment_status",
                   "social_context", "co_occurring_symptoms", "motivation_at_intake", "background",
                   "history_summary", "treatment_summary"):
        assert body[column] == patient[column], column
    assert body["intake_date"] == patient["intake_date"].isoformat()

    def ids(table, column):
        return [r[0] for r in conn.execute(
            text(f"SELECT {column} FROM {table} WHERE patient_id = :p ORDER BY {column}"), {"p": patient_id})]

    assert sorted(u["id"] for u in body["use_records"]) == ids("substance_or_behavior_use", "use_id")
    assert sorted(f["id"] for f in body["factors"]) == ids("triggers_and_risk_factors", "factor_id")
    assert sorted(i["id"] for i in body["interventions"]) == ids("previous_interventions", "intervention_id")
    assert [o["id"] for o in body["progress"]] == ids("progress_observations", "observation_id")
    assert body["primary_use_subject"] == body["use_records"][0]["subject"]


def test_profile_has_the_same_content_as_the_sql_query(client, conn):
    sql = (QUERIES_DIR / "patient_profile.sql").read_text(encoding="utf-8")
    row = conn.execute(text(sql), {"patient_id": "P-004"}).mappings().one()
    body = client.get("/api/patients/P-004").json()
    assert len(body["interventions"]) == len(row["interventions"]) == 2
    assert [i["type"] for i in body["interventions"]] == [i["type"] for i in row["interventions"]]


@pytest.mark.parametrize("path", ["/api/patients/P-999", "/api/patients/P-999/history"])
def test_missing_patient_is_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("bad", ["ABC", "P-1", "P-0001", "p-001", "P-00A", "P_001"])
@pytest.mark.parametrize("suffix", ["", "/history"])
def test_malformed_patient_id_is_422(client, bad, suffix):
    assert client.get(f"/api/patients/{bad}{suffix}").status_code == 422


@pytest.mark.parametrize("patient_id", PATIENT_IDS)
def test_history_is_chronological_and_complete(client, conn, patient_id):
    body = all_history(client, patient_id)
    dates = [item["event_date"] for item in body["items"]]
    assert dates == sorted(dates)
    assert body["total"] == len(body["items"])

    def count(sql):
        return conn.scalar(text(sql), {"p": patient_id})

    expected = (
        count("SELECT count(*) FROM patient_history_events WHERE patient_id = :p")
        + count("SELECT count(*) FROM substance_or_behavior_use WHERE patient_id = :p")
        + count("SELECT count(*) FROM substance_or_behavior_use WHERE patient_id = :p AND end_date IS NOT NULL")
        + count("SELECT count(*) FROM previous_interventions WHERE patient_id = :p")
        + count("SELECT count(*) FROM previous_interventions WHERE patient_id = :p AND end_date IS NOT NULL")
        + count("SELECT count(*) FROM progress_observations WHERE patient_id = :p")
    )
    assert body["total"] == expected

    # Same order as the reviewed SQL file.
    sql = (QUERIES_DIR / "patient_history.sql").read_text(encoding="utf-8")
    rows = conn.execute(text(sql), {"patient_id": patient_id}).mappings().all()
    assert [(i["record_id"], i["kind"]) for i in body["items"]] == [(r["record_id"], r["kind"]) for r in rows]


def test_history_pagination_slices_the_same_sequence(client):
    full = all_history(client, "P-001")["items"]
    page = client.get("/api/patients/P-001/history?limit=5&offset=5").json()
    assert page["items"] == full[5:10]
    assert (page["total"], page["limit"], page["offset"]) == (len(full), 5, 5)
    assert client.get("/api/patients/P-001/history?limit=101").status_code == 422
    assert full[0]["kind"] == "onset" and full[0]["source"] == "history"
