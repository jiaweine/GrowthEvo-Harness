# Durable PostgreSQL persistence

GrowthEvo can run its product/reference state on durable PostgreSQL without changing the causal policy implementation or public product identity.

The persistence layer is intentionally narrow. It stores product state and audit records; it does not replace the existing CATE, OPE, Safe-PI, locked-evidence, or policy evaluation logic.

## Runtime behavior

GrowthEvo reads the database connection from `GROWTHEVO_DATABASE_URL`, falling back to `DATABASE_URL` when the GrowthEvo-specific variable is unset.

- `GROWTHEVO_MODE=demo` never opens an external database. Demo remains credential-free and synthetic even if a generic platform `DATABASE_URL` leaks into the environment.
- `GROWTHEVO_MODE=api` uses PostgreSQL when a database URL is configured. The reference Campaign and Approval fixtures are seeded idempotently so the API-mode product surface remains immediately explorable.
- `GROWTHEVO_MODE=production` uses PostgreSQL when configured, runs the schema migration, and **does not seed synthetic Campaigns or Approvals**. Production business APIs remain fail-closed until authentication is also active.
- If API or production mode declares a database URL but the database cannot be connected to or migrated, application startup fails. GrowthEvo does not silently fall back to process memory after durable persistence was explicitly requested.

This means a healthy PostgreSQL connection is necessary but not sufficient for production readiness. Authentication remains a separate hard gate.

## Stored product state

The durable core stores:

- Campaign drafts;
- Approval state and the first accepted governance decision;
- Decision logs, including the exact action distribution and behavior propensity produced by the reference decision contract;
- Idempotency keys and their request fingerprints.

PostgreSQL tables use stable semantic names:

- `growthevo_campaigns`
- `growthevo_approvals`
- `growthevo_decisions`
- `growthevo_idempotency`
- `growthevo_schema_migrations`

Schema evolution is tracked by semantic migration identity. The initial migration is named `durable_core`; GrowthEvo does not expose numbered product-generation labels through migrations or product APIs.

## Concurrency and recovery guarantees

The persistence implementation is designed around multi-process and multi-replica correctness:

- schema bootstrap is serialized with a PostgreSQL advisory transaction lock;
- `Idempotency-Key` is unique in PostgreSQL, so simultaneous first requests across different API replicas converge on one stored decision;
- reusing the same idempotency key for a materially different request remains a conflict;
- an Approval is read with `FOR UPDATE`, so two replicas cannot finalize one pending Approval to conflicting outcomes;
- Campaign writes use database-generated ordering and remain visible across replicas;
- Decision logs and Campaign/Approval state survive API process restarts.

Idempotency records are retained for seven days. Decision logs are durable independently from the idempotency retention window so causal/OPE audit evidence is not tied to request-deduplication lifetime.

## CI verification

`Product Persistence CI` starts a real PostgreSQL service and exercises the same production container used by the product surface.

The workflow verifies:

1. schema bootstrap/migration;
2. API-mode persistence activation and health reporting;
3. Campaign, Approval, Decision Log, and Idempotency recovery after a new application instance is created;
4. 128 simultaneous same-key decision requests across two independent API replicas converging on one decision ID;
5. conflicting reuse of that key returning a conflict;
6. concurrent Approval decisions producing one winner and one conflict;
7. parallel Campaign writes from two replicas remaining unique and mutually visible;
8. quick mixed product pressure against the PostgreSQL-backed API;
9. production mode remaining `not_ready` while authentication is inactive;
10. production migration leaving synthetic Campaign and Approval fixtures absent.

The PostgreSQL service image and Python database client are pinned as supply-chain/runtime metadata. These dependency versions are not GrowthEvo product-generation labels.

## Local development

With a local PostgreSQL instance available, API mode can be started with:

```bash
export GROWTHEVO_MODE=api
export GROWTHEVO_ENV=local
export GROWTHEVO_DATABASE_URL='postgresql://growthevo:password@127.0.0.1:5432/growthevo'
growthevo-web
```

Then inspect:

```text
GET /api/ready
GET /api/system/runtime
GET /api/system/connectors
```

A successful durable API runtime reports persistence as configured, active, healthy, and backed by PostgreSQL.

For production, configure PostgreSQL in the same way but keep `GROWTHEVO_MODE=production`. GrowthEvo will migrate the database but will continue returning `503` from business APIs until the authentication adapter is actually active.

## Supabase / managed PostgreSQL

The persistence contract uses ordinary PostgreSQL and does not depend on a proprietary database extension. A future Supabase deployment can provide its PostgreSQL connection URL at the same adapter boundary. Use the server-side database credential only in the backend runtime; never expose it to the Web/PWA or Expo client.

No database credential belongs in GitHub source, Pages artifacts, mobile bundles, or public runtime payloads.
