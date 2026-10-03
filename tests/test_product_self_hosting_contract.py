from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_IMAGE = (
    "postgres:17.11@sha256:"
    "e31e3d5327d1806f6177827c9710643e4f35f7ab3f14d26d05332753d3e95ee0"
)


def test_compose_uses_pinned_postgres_and_private_api_defaults() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    postgres, api = compose.split("\n  api:\n", maxsplit=1)

    assert POSTGRES_IMAGE in postgres
    assert "ports:" not in postgres
    assert "growthevo-postgres:/var/lib/postgresql/data" in postgres
    assert "condition: service_healthy" in api
    assert "GROWTHEVO_MODE: ${GROWTHEVO_MODE:-api}" in api
    assert "${GROWTHEVO_API_BIND:-127.0.0.1}" in api
    assert "GROWTHEVO_AUTH_ISSUER" in api
    assert "GROWTHEVO_AUTH_JWKS_URL" in api
    assert "GROWTHEVO_AUTH_AUDIENCE" in api


def test_self_host_environment_example_is_fail_closed_by_default() -> None:
    env = (ROOT / ".env.self-host.example").read_text(encoding="utf-8")

    assert "GROWTHEVO_MODE=api" in env
    assert "GROWTHEVO_API_BIND=127.0.0.1" in env
    assert "GROWTHEVO_AUTH_ISSUER=" in env
    assert "GROWTHEVO_AUTH_JWKS_URL=" in env
    assert "GROWTHEVO_AUTH_AUDIENCE=" in env
    assert "replace-with-a-long-random-password" in env


def test_backup_and_restore_helpers_are_guarded_and_parse_as_bash() -> None:
    backup_path = ROOT / "scripts" / "backup_postgres.sh"
    restore_path = ROOT / "scripts" / "restore_postgres.sh"
    backup = backup_path.read_text(encoding="utf-8")
    restore = restore_path.read_text(encoding="utf-8")

    subprocess.run(["bash", "-n", str(backup_path)], check=True)
    subprocess.run(["bash", "-n", str(restore_path)], check=True)

    assert "set -Eeuo pipefail" in backup
    assert "--format=custom" in backup
    assert "sha256sum" in backup
    assert ".partial" in backup

    assert 'GROWTHEVO_RESTORE_CONFIRM:-' in restore
    assert '!= "YES"' in restore
    assert "sha256sum --check" in restore
    assert "docker compose stop api" in restore
    assert "--clean" in restore
    assert "--if-exists" in restore
    assert "--exit-on-error" in restore


def test_self_hosting_runbook_preserves_production_boundary() -> None:
    runbook = (ROOT / "docs" / "SELF_HOSTING.md").read_text(encoding="utf-8")

    assert "production mode remains fail-closed" in runbook
    assert "GROWTHEVO_MODE=production" in runbook
    assert "GROWTHEVO_AUTH_ISSUER" in runbook
    assert "GROWTHEVO_AUTH_JWKS_URL" in runbook
    assert "GROWTHEVO_AUTH_AUDIENCE" in runbook
    assert "./scripts/backup_postgres.sh" in runbook
    assert "./scripts/restore_postgres.sh" in runbook
