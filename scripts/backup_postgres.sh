#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${1:-backups/growthevo-${stamp}.dump}"
checksum="${out}.sha256"
mkdir -p "$(dirname "$out")"
tmp="${out}.partial"
checksum_tmp="${checksum}.partial"

if [ -e "$out" ] || [ -e "$checksum" ]; then
  echo "backup destination already exists; refusing to overwrite: $out" >&2
  exit 1
fi

rm -f "$tmp" "$checksum_tmp"
cleanup() {
  rm -f "$tmp" "$checksum_tmp"
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

digest="$(sha256sum "$tmp" | awk '{print $1}')"
printf '%s  %s\n' "$digest" "$out" > "$checksum_tmp"

mv "$tmp" "$out"
mv "$checksum_tmp" "$checksum"
trap - EXIT
printf 'backup: %s\nchecksum: %s\n' "$out" "$checksum"
