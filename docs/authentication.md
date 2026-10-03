# Production authentication

GrowthEvo production business APIs use a generic OIDC/JWKS bearer boundary. Authentication is independent from persistence: production is ready only when both durable PostgreSQL and the identity verifier are active and healthy.

## Required configuration

Set all three values together:

- `GROWTHEVO_AUTH_ISSUER`: exact JWT `iss` value.
- `GROWTHEVO_AUTH_JWKS_URL`: HTTPS URL returning the issuer's JWKS document.
- `GROWTHEVO_AUTH_AUDIENCE`: exact audience accepted by GrowthEvo.

Partial identity configuration is reported as `configured_not_active`; it does not make production ready. `SUPABASE_URL` can indicate that identity infrastructure is configured, but it does not by itself activate authentication. Configure the generic issuer, JWKS URL, and audience explicitly.

Production requires HTTPS for both issuer and JWKS URLs. A complete configuration is fail-fast: startup must fetch a valid JWKS containing at least one usable RSA signing key or the process does not advertise an active authentication boundary. The JWKS URL is explicit rather than discovered, and redirects are rejected so signing-key trust cannot move to another origin or path implicitly.

## Token contract

Business API requests in production must send exactly one header:

`Authorization: Bearer <JWT>`

The verifier accepts RS256 only and validates the signature, key id, issuer, audience, expiration, and non-empty subject. The accepted algorithm is fixed by server configuration and is never selected from an untrusted JWT header. An unknown key id can trigger one JWKS refresh for normal signing-key rotation; further unknown ids are rate-limited during a short cooldown so attacker-controlled `kid` values cannot turn every request into remote identity-provider traffic.

JWKS responses and JWT sizes are bounded. JWKS keys are cached for a short interval so normal requests do not depend on a remote identity-provider round trip.

Missing, malformed, duplicate, expired, incorrectly signed, wrong-issuer, or wrong-audience credentials return HTTP `401` with `WWW-Authenticate: Bearer`. Authentication failures intentionally expose no token-validation detail. If a request needs a JWKS refresh while the identity provider is temporarily unavailable, the business API returns HTTP `503` and remains fail-closed rather than misclassifying the outage as a bad credential.

## Public system endpoints

The following endpoints remain available without a bearer token so infrastructure can diagnose and route the service:

- `/api/health`
- `/api/ready`
- `/api/system/runtime`
- `/api/system/connectors`
- `/api/docs`
- `/api/openapi.json`

When production dependencies are not healthy, business APIs return HTTP `503` before authentication is attempted. Once production is ready, business APIs enforce bearer authentication.

`/api/system/runtime` exposes only public-safe connector state such as `configured`, `active`, `backend`, and `healthy`; it never returns JWTs, credentials, keys, or identity-provider secrets.

## Browser clients

Production CORS origins must be exact HTTPS origins. When a browser client calls the API, `Authorization` is an allowed request header alongside the existing JSON and idempotency headers. CORS `OPTIONS` preflight requests are handled without bearer authentication; the actual business request still requires a valid token. Do not embed bearer tokens in the static Pages bundle or repository; obtain them from the configured identity provider at runtime.

## Verification

`Product Auth CI` runs without an external identity provider. It creates an ephemeral CA, TLS JWKS endpoint, RSA signing key, PostgreSQL service, and production container, then verifies:

- production becomes ready only with healthy persistence and OIDC/JWKS;
- anonymous system probes remain reachable;
- browser CORS preflight accepts the `Authorization` request header;
- business APIs reject missing credentials;
- a valid RS256 token is accepted;
- wrong audience, wrong issuer, expired tokens, and duplicate authorization headers are rejected;
- an unknown key that requires refresh returns `503` when the JWKS endpoint is unavailable.
