"""The Docker files and the dev script: what must never be in an image, healthchecks, localhost-only ports, no .env handling."""
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DOCKERFILE = (PROJECT / "backend" / "Dockerfile").read_text(encoding="utf-8")
IGNORE = (PROJECT / ".dockerignore").read_text(encoding="utf-8").splitlines()
COMPOSE = (PROJECT / "docker-compose.yml").read_text(encoding="utf-8")
DEV = (PROJECT / "scripts" / "dev.ps1").read_text(encoding="utf-8")


def service_block(name: str) -> str:
    match = re.search(rf"^  {name}:\n((?:    .*\n|\n)+)", COMPOSE, re.MULTILINE)
    assert match, f"service {name} not found"
    return match.group(1)


def test_the_image_runs_as_an_unprivileged_user_and_copies_no_secrets():
    assert re.search(r"^USER app$", DOCKERFILE, re.MULTILINE) and "useradd" in DOCKERFILE
    copies = re.findall(r"^COPY\s+(.+)$", DOCKERFILE, re.MULTILINE)
    assert copies and all(".env" not in c and "data" not in c and "models" not in c for c in copies)
    assert not re.search(r"^(ENV|ARG)\s+\w*(SECRET|PASSWORD|KEY|TOKEN)\w*", DOCKERFILE, re.MULTILINE | re.IGNORECASE)
    assert "ARG WITH_EMBEDDINGS=false" in DOCKERFILE                       # the heavy torch stack is opt-in


def test_the_build_context_excludes_secrets_pdfs_models_and_caches():
    for entry in (".env", ".env.*", "data/", "backend/models/", "backend/.venv/", "*.pdf", "*.safetensors", ".git", "**/__pycache__/"):
        assert entry in IGNORE, entry
    assert "!.env.example" in IGNORE


def test_the_default_profile_is_still_only_the_database():
    assert "profiles" not in service_block("db")
    for name in ("api", "web"):
        assert 'profiles: ["app"]' in service_block(name)


def test_the_app_services_have_healthchecks_on_the_health_endpoint():
    assert "healthcheck:" in service_block("api") and "/api/health" in service_block("api")
    assert "healthcheck:" in service_block("web")
    assert "condition: service_healthy" in service_block("api")


def test_secrets_reach_the_container_only_at_run_time_and_data_is_mounted():
    api = service_block("api")
    assert "env_file:" in api and "path: .env" in api
    assert "./data:/srv/data" in api and "./backend/models:/srv/backend/models:ro" in api
    assert "host.docker.internal" in api and "LLM_BASE_URL" in api
    assert "localhost:8000" in api                                          # CORS and the frontend URL stay localhost
    assert not re.search(r"(PASSWORD|SECRET|API_KEY)\s*:\s*[^\s$\"']", api)  # no literal secret in the compose file


def test_the_dev_script_never_reads_or_writes_env_files():
    code = "\n".join(line for line in DEV.splitlines() if not line.strip().startswith("#"))
    code = re.sub(r"<#.*?#>", "", DEV, flags=re.DOTALL)  # the help block may mention .env
    for cmdlet in ("Get-Content", "Set-Content", "Add-Content", "Out-File", "Copy-Item", "Remove-Item", "Select-String", "Import-"):
        for line in code.splitlines():
            assert not (cmdlet in line and ".env" in line), line
    assert {"up", "migrate", "seed", "ingest", "embed", "api", "web", "test", "diagnose"} <= set(re.findall(r'^\s+"(\w+)"\s+\{', code, re.MULTILINE))
