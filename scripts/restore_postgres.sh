#!/usr/bin/env bash
set -Eeuo pipefail

backup="${1:-}"
if [ -z "$backup" ] || [ ! -f "$backup" ]; then
  echo "usage: GROWTHEVO_RESTORE_CONFIRM=YES $0 <backup.dump>" >&2
  exit 2
fi
if [ "${GROWTHEVO_RESTORE_CONFIRM:-}" != "YES" ]; then
  echo "restore is destructive; set GROWTHEVO_RESTORE_CONFIRM=YES to continue" >&2
  exit 2
fi

checksum="${backup}.sha256"
if [ ! -f "$checksum" ]; then
  echo "checksum is required for restore: $checksum" >&2
  exit 1
fi

line_count="$(wc -l < "$checksum" | tr -d ' ')"
if [ "$line_count" -ne 1 ]; then
  echo "checksum file must contain exactly one entry" >&2
  exit 1
fi

read -r expected_hash recorded_path < "$checksum"
if [[ ! "$expected_hash" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo "checksum file contains an invalid SHA-256 digest" >&2
  exit 1
fi
if [ "$recorded_path" != "$backup" ]; then
  echo "checksum entry does not match requested backup: $recorded_path" >&2
  exit 1
fi
actual_hash="$(sha256sum "$backup" | awk '{print $1}')"
if [ "${actual_hash,,}" != "${expected_hash,,}" ]; then
  echo "backup checksum mismatch" >&2
  exit 1
fi

if ! docker compose ps --status running --services | grep -Fxq postgres; then
  echo "GrowthEvo PostgreSQL service is not running" >&2
  exit 1
fi

# Validate the custom-format archive before stopping the API or changing the database.
if ! docker compose exec -T postgres pg_restore --list < "$backup" >/dev/null; then
  echo "backup archive is not a readable PostgreSQL custom-format dump" >&2
  exit 1
fi

api_was_running=false
if docker compose ps --status running --services | grep -Fxq api; then
  api_was_running=true
  docker compose stop api >/dev/null
fi

restore_failed() {
  status=$?
  trap - ERR
  if [ "$status" -ne 0 ] && [ "$api_was_running" = true ]; then
    echo "restore failed; API remains stopped to avoid serving a partially restored database" >&2
  fi
  exit "$status"
}
trap restore_failed ERR

cat "$backup" | docker compose exec -T postgres sh -ceu '
  exec pg_restore \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --clean \
    --if-exists \
    --no-owner \
    --no-acl \
    --exit-on-error
'

trap - ERR

if [ "$api_was_running" = true ]; then
  docker compose start api >/dev/null
  for _ in $(seq 1 40); do
    if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/ready', timeout=3)" >/dev/null 2>&1; then
      echo "restore complete; API is ready"
      exit 0
    fi
    sleep 0.5
  done
  docker compose stop api >/dev/null 2>&1 || true
  echo "database restored, but API did not become ready; API has been stopped" >&2
  exit 1
fi

echo "restore complete"
