# GrowthEvo self-hosting runbook

This runbook provides a small, production-shaped deployment for a personal GrowthEvo installation. It deliberately uses only the existing FastAPI container and PostgreSQL. It does not introduce Kubernetes, Redis, Kafka, or a separate workflow engine.

## What this stack guarantees

- PostgreSQL state is stored on a named Docker volume.
- The API waits for PostgreSQL health before starting.
- The API binds to `127.0.0.1` by default; put a TLS reverse proxy in front of it before exposing it publicly.
- `api` mode is a durable reference runtime for validation and private use.
- `production` mode remains fail-closed until both PostgreSQL and OIDC/JWKS authentication are active.
- Backup files are published only after a non-empty custom-format dump and SHA-256 integrity metadata are produced.
- Existing backup destinations are never overwritten implicitly.
- Restore is destructive by design and requires an explicit confirmation environment variable.
- Restore checksum is mandatory, and the archive is validated before the API is stopped or the database is modified.

## Start the stack

```bash
cp .env.self-host.example .env
# Replace the example database password before continuing.
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8765/api/ready
```

The default `.env.self-host.example` uses `GROWTHEVO_MODE=api`. This is intentionally not presented as a production identity boundary.

## Enable production mode

Configure all of the following in `.env`:

```text
GROWTHEVO_MODE=production
GROWTHEVO_ENV=production
GROWTHEVO_CORS_ORIGINS=https://app.example.com
GROWTHEVO_AUTH_ISSUER=https://identity.example.com/
GROWTHEVO_AUTH_JWKS_URL=https://identity.example.com/.well-known/jwks.json
GROWTHEVO_AUTH_AUDIENCE=growthevo
```

The issuer, JWKS URL, and audience are a single trust contract. GrowthEvo verifies signed bearer tokens and fails closed if the identity provider cannot be trusted or reached for a required key refresh.

Production browser origins must use HTTPS. Do not expose port 8765 directly to the public internet; terminate TLS at a reverse proxy or managed ingress and forward traffic to the loopback-bound API.

## Backup

```bash
bash scripts/backup_postgres.sh
# Or choose the destination explicitly:
bash scripts/backup_postgres.sh backups/pre-change.dump
```

Each successful backup produces both a PostgreSQL custom-format dump and a matching `.sha256` file. If either destination already exists, the backup helper refuses to overwrite it; choose a new path instead. The repository ignores `backups/` so a database dump is not accidentally committed. Keep backups outside the application host as well; a backup stored only beside the live volume is not a disaster-recovery copy.

A reasonable personal-project policy is:

- daily encrypted off-host backup;
- retain at least 7 daily and 4 weekly copies;
- take an extra backup before schema or infrastructure changes;
- periodically restore a backup into a clean database and verify the API against it.

## Restore

Stop external writers first. Then run:

```bash
GROWTHEVO_RESTORE_CONFIRM=YES bash scripts/restore_postgres.sh backups/pre-change.dump
```

The matching `.sha256` file is required. Restore fails before any destructive action if the checksum file is missing, malformed, points at a different dump path, or does not match the dump bytes. The PostgreSQL custom-format archive is also parsed with `pg_restore --list` before the API is stopped or database objects are changed.

If the API service was running, the script stops it only after those checks pass, performs the restore, and only reports success after the API becomes ready again.

## Upgrade safely

```bash
bash scripts/backup_postgres.sh backups/pre-upgrade.dump
docker compose build --pull=false
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8765/api/ready
```

The repository pins the Python base image and PostgreSQL image by digest. Dependency updates should continue to arrive through reviewed repository changes and CI rather than ad-hoc package upgrades on the server.

## Recovery checks

After any restore or host migration, verify at minimum:

```bash
curl --fail http://127.0.0.1:8765/api/ready
curl --fail http://127.0.0.1:8765/api/system/runtime
```

Then confirm that a known Campaign and a known recent Decision are visible. The repository persistence CI performs the equivalent recovery check automatically against a fresh restored PostgreSQL database, including dump integrity, archive readability, restored API readiness, and recovered Campaign/Decision state.

## Boundaries

This stack does not pretend external providers are connected. Object storage, LLM providers, advertising channels, email/SMS, and other enterprise adapters remain disconnected until real credentials and adapters are configured. Production mode also does not become ready merely because environment variables exist: durable PostgreSQL and authentication must initialize successfully.
