"""docs/ARCHITECTURE.md must list exactly the endpoints of /openapi.json, and show the diagram in both forms."""
import re
from pathlib import Path

DOC = (Path(__file__).resolve().parents[2] / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")


def documented() -> set[tuple[str, str]]:
    block = DOC.split("<!-- endpoints:start -->")[1].split("<!-- endpoints:end -->")[0]
    return {(m.group(1), m.group(2)) for m in re.finditer(r"^\| ([A-Z]+) \| `([^`]+)` \|", block, re.MULTILINE)}


def test_the_endpoint_table_matches_openapi_exactly(client):
    spec = client.get("/openapi.json").json()
    actual = {(method.upper(), path) for path, item in spec["paths"].items() for method in item}
    docs = documented()
    assert actual - docs == set(), f"endpoints missing from docs/ARCHITECTURE.md: {sorted(actual - docs)}"
    assert docs - actual == set(), f"docs/ARCHITECTURE.md lists endpoints that do not exist: {sorted(docs - actual)}"


def test_the_summaries_match_openapi(client):
    spec = client.get("/openapi.json").json()
    block = DOC.split("<!-- endpoints:start -->")[1].split("<!-- endpoints:end -->")[0]
    for method, path, _, summary in re.findall(r"^\| ([A-Z]+) \| `([^`]+)` \| (\w+) \| (.+) \|$", block, re.MULTILINE):
        assert spec["paths"][path][method.lower()]["summary"] == summary, (method, path)


def test_the_document_has_a_mermaid_and_a_plain_text_diagram_and_states_the_limits():
    assert "```mermaid" in DOC and "flowchart LR" in DOC and "Plain-text version" in DOC
    assert "not production-ready" in DOC and "not implemented" in DOC.lower()
