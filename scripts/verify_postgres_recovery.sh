#!/usr/bin/env bash
set -Eeuo pipefail

POSTGRES_IMAGE="postgres:17.11@sha256:e31e3d5327d1806f6177827c9710643e4f35f7ab3f14d26d05332753d3e95ee0"
DB_HOST="${GROWTHEVO_RECOVERY_DB_HOST:-127.0.0.1}"
DB_PORT="${GROWTHEVO_RECOVERY_DB_PORT:-55432}"
DB_USER="${GROWTHEVO_RECOVERY_DB_USER:-growthevo}"
DB_PASSWORD="${GROWTHEVO_RECOVERY_DB_PASSWORD:-growthevo-ci}"
SOURCE_DB="${GROWTHEVO_RECOVERY_SOURCE_DB:-growthevo_ci}"
RESTORE_DB="${GROWTHEVO_RECOVERY_RESTORE_DB:-growthevo_restore}"
REPORT_DIR="${GROWTHEVO_RECOVERY_REPORT_DIR:-persistence-reports}"
API_IMAGE="${GROWTHEVO_RECOVERY_API_IMAGE:-growthevo-api:persistence-ci}"
API_CONTAINER="growthevo-recovery-ci"
API_PORT="${GROWTHEVO_RECOVERY_API_PORT:-8769}"

mkdir -p "$REPORT_DIR"
backup="$REPORT_DIR/growthevo-recovery.dump"
checksum="${backup}.sha256"

cleanup() {
  docker rm -f "$API_CONTAINER" >/dev/null 2>&1 || true
  PGPASSWORD="$DB_PASSWORD" docker run --rm --network host \
    -e PGPASSWORD="$DB_PASSWORD" "$POSTGRES_IMAGE" \
    dropdb --if-exists --force -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$RESTORE_DB" \
    >/dev/null 2>&1 || true
}
trap cleanup EXIT

PGPASSWORD="$DB_PASSWORD" docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" "$POSTGRES_IMAGE" \
  pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$SOURCE_DB" \
  --format=custom --no-owner --no-acl > "$backup"

test -s "$backup"
sha256sum "$backup" > "$checksum"
sha256sum --check "$checksum"

PGPASSWORD="$DB_PASSWORD" docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" "$POSTGRES_IMAGE" \
  dropdb --if-exists --force -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$RESTORE_DB" >/dev/null
PGPASSWORD="$DB_PASSWORD" docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" "$POSTGRES_IMAGE" \
  createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -O "$DB_USER" "$RESTORE_DB"
cat "$backup" | PGPASSWORD="$DB_PASSWORD" docker run --rm -i --network host \
  -e PGPASSWORD="$DB_PASSWORD" "$POSTGRES_IMAGE" \
  pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$RESTORE_DB" \
  --no-owner --no-acl --exit-on-error

RESTORE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@host.docker.internal:${DB_PORT}/${RESTORE_DB}"
docker run --rm -d \
  --name "$API_CONTAINER" \
  --add-host=host.docker.internal:host-gateway \
  -p "${API_PORT}:8765" \
  -e GROWTHEVO_MODE=api \
  -e GROWTHEVO_ENV=recovery-ci \
  -e GROWTHEVO_DATABASE_URL="$RESTORE_URL" \
  "$API_IMAGE" >/dev/null

for _ in $(seq 1 40); do
  if curl --fail --silent "http://127.0.0.1:${API_PORT}/api/ready" >/dev/null; then
    break
  fi
  sleep 0.5
done
curl --fail --silent "http://127.0.0.1:${API_PORT}/api/ready" >/dev/null
curl --fail --silent "http://127.0.0.1:${API_PORT}/api/campaigns" > "$REPORT_DIR/recovered-campaigns.json"
curl --fail --silent "http://127.0.0.1:${API_PORT}/api/decisions/recent?limit=100" > "$REPORT_DIR/recovered-decisions.json"

python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ.get("GROWTHEVO_RECOVERY_REPORT_DIR", "persistence-reports"))
campaigns = json.loads((root / "recovered-campaigns.json").read_text())
decisions = json.loads((root / "recovered-decisions.json").read_text())

assert any(item.get("name") == "Container restart durability check" for item in campaigns)
assert any(item.get("entity_id") == "container-restart-user" for item in decisions)
PY

{
  echo '### PostgreSQL disaster recovery verification'
  echo
  echo '- custom-format pg_dump: PASS'
  echo '- SHA-256 integrity check: PASS'
  echo '- restore into a fresh database: PASS'
  echo '- restored API readiness: PASS'
  echo '- restored Campaign and Decision state: PASS'
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "PostgreSQL backup/restore verification passed"
