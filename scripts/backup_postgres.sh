#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${1:-backups/growthevo-${stamp}.dump}"
mkdir -p "$(dirname "$out")"
tmp="${out}.partial"
rm -f "$tmp"

cleanup() {
  rm -f "$tmp"
}
trap cleanup EXIT

if ! docker compose ps --status running --services | grep -Fxq postgres; then
  echo "GrowthEvo PostgreSQL service is not running" >&2
  exit 1
fi

docker compose exec -T postgres sh -ceu '
  exec pg_dump \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --format=custom \
    --no-owner \
    --no-acl
' > "$tmp"

if [ ! -s "$tmp" ]; then
  echo "backup is empty; refusing to publish it" >&2
  exit 1
fi

mv "$tmp" "$out"
sha256sum "$out" > "${out}.sha256"
trap - EXIT
printf 'backup: %s\nchecksum: %s\n' "$out" "${out}.sha256"
