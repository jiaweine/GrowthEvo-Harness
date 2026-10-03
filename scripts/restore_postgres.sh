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
if [ -f "$checksum" ]; then
  sha256sum --check "$checksum"
else
  echo "warning: no checksum file found at $checksum" >&2
fi

if ! docker compose ps --status running --services | grep -Fxq postgres; then
  echo "GrowthEvo PostgreSQL service is not running" >&2
  exit 1
fi

api_was_running=false
if docker compose ps --status running --services | grep -Fxq api; then
  api_was_running=true
  docker compose stop api >/dev/null
fi

restart_api() {
  if [ "$api_was_running" = true ]; then
    docker compose start api >/dev/null 2>&1 || true
  fi
}
trap restart_api EXIT

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

if [ "$api_was_running" = true ]; then
  docker compose start api >/dev/null
  for _ in $(seq 1 40); do
    if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/ready', timeout=3)" >/dev/null 2>&1; then
      trap - EXIT
      echo "restore complete; API is ready"
      exit 0
    fi
    sleep 0.5
  done
  echo "database restored, but API did not become ready" >&2
  exit 1
fi

trap - EXIT
echo "restore complete"
