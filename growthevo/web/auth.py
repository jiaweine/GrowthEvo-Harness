from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

JWKS_MAX_BYTES = 256_000
JWT_MAX_BYTES = 16_384
JWKS_CACHE_TTL_SECONDS = 300.0
JWKS_UNKNOWN_KID_REFRESH_COOLDOWN_SECONDS = 30.0
JWT_LEEWAY_SECONDS = 30
_ALLOWED_ALGORITHMS = ("RS256",)


class AuthConfigurationError(RuntimeError):
    """Authentication configuration or JWKS bootstrap is invalid."""


class AuthenticationError(RuntimeError):
    """A bearer credential cannot be accepted."""


class AuthenticationUnavailable(RuntimeError):
    """The configured identity provider is temporarily unavailable."""


def _validated_url(value: str, *, label: str, require_https: bool) -> str:
    candidate = value.strip()
    if not candidate:
        raise AuthConfigurationError(f"{label} must not be empty")
    try:
        parsed = urlparse(candidate)
        _ = parsed.port
    except ValueError as exc:
        raise AuthConfigurationError(f"invalid {label}") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise AuthConfigurationError(f"invalid {label}")
    if require_https and parsed.scheme != "https":
        raise AuthConfigurationError(f"production {label} must use https")
    return candidate


class OidcJwksAuthenticator:
    """Fail-closed OIDC bearer verifier backed by a bounded JWKS cache.

    The accepted JWT algorithm is fixed in code instead of being inferred from
    attacker-controlled token headers. Unknown key ids trigger at most one JWKS
    refresh per cooldown window, which supports normal issuer key rotation while
    preventing attacker-controlled kid values from turning every request into a
    remote identity-provider dependency.
    """

    backend = "oidc-jwks"

    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        audience: str,
        require_https: bool,
        cache_ttl_seconds: float = JWKS_CACHE_TTL_SECONDS,
        timeout_seconds: float = 5.0,
        unknown_kid_refresh_cooldown_seconds: float = JWKS_UNKNOWN_KID_REFRESH_COOLDOWN_SECONDS,
        fetcher: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        if cache_ttl_seconds <= 0:
            raise AuthConfigurationError("JWKS cache TTL must be positive")
        if timeout_seconds <= 0:
            raise AuthConfigurationError("JWKS timeout must be positive")
        if unknown_kid_refresh_cooldown_seconds < 0:
            raise AuthConfigurationError("unknown-kid JWKS refresh cooldown must not be negative")
        self.issuer = _validated_url(
            issuer,
            label="GROWTHEVO_AUTH_ISSUER",
            require_https=require_https,
        )
        self.jwks_url = _validated_url(
            jwks_url,
            label="GROWTHEVO_AUTH_JWKS_URL",
            require_https=require_https,
        )
        self.audience = audience.strip()
        if not self.audience:
            raise AuthConfigurationError("GROWTHEVO_AUTH_AUDIENCE must not be empty")
        self._require_https = require_https
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._timeout_seconds = float(timeout_seconds)
        self._unknown_kid_refresh_cooldown_seconds = float(
            unknown_kid_refresh_cooldown_seconds
        )
        self._fetcher = fetcher or self._fetch_jwks
        self._lock = threading.RLock()
        self._keys: dict[str, Any] = {}
        self._expires_monotonic = 0.0
        self._last_unknown_kid_refresh_monotonic = float("-inf")
        self._unknown_kid_refresh_in_progress = False
        self._last_unknown_kid_refresh_unavailable = False
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - guarded by the web extra/container lock
            raise AuthConfigurationError(
                "OIDC/JWKS authentication requires PyJWT with cryptography support"
            ) from exc
        self._jwt = jwt
        self._refresh(force=True)

    def _fetch_jwks(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "GrowthEvo-OIDC-JWKS",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                final_url = response.geturl()
                # Do not transfer JWKS trust through redirects. Even HTTPS-to-HTTPS
                # redirects can move key retrieval to a different origin or path.
                if final_url != url:
                    raise AuthConfigurationError("configured JWKS URL must not redirect")
                body = response.read(JWKS_MAX_BYTES + 1)
        except AuthConfigurationError:
            raise
        except Exception as exc:
            raise AuthenticationUnavailable("could not fetch configured JWKS") from exc
        if len(body) > JWKS_MAX_BYTES:
            raise AuthConfigurationError("configured JWKS exceeds size limit")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthConfigurationError("configured JWKS is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise AuthConfigurationError("configured JWKS must be a JSON object")
        return payload

    def _parse_jwks(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_keys = payload.get("keys")
        if not isinstance(raw_keys, list):
            raise AuthConfigurationError("configured JWKS must contain a keys array")
        parsed: dict[str, Any] = {}
        for item in raw_keys:
            if not isinstance(item, dict):
                continue
            kid = item.get("kid")
            if not isinstance(kid, str) or not kid.strip():
                continue
            if item.get("kty") != "RSA":
                continue
            if item.get("use") not in {None, "sig"}:
                continue
            if item.get("alg") not in {None, "RS256"}:
                continue
            normalized_kid = kid.strip()
            if normalized_kid in parsed:
                raise AuthConfigurationError("configured JWKS contains duplicate key ids")
            try:
                parsed[normalized_kid] = self._jwt.PyJWK.from_dict(
                    item,
                    algorithm="RS256",
                ).key
            except Exception as exc:
                raise AuthConfigurationError("configured JWKS contains an invalid RSA key") from exc
        if not parsed:
            raise AuthConfigurationError("configured JWKS contains no usable RS256 signing keys")
        return parsed

    def _refresh(self, *, force: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            if not force and self._keys and now < self._expires_monotonic:
                return
            payload = self._fetcher(self.jwks_url)
            if not isinstance(payload, dict):
                raise AuthConfigurationError("JWKS fetcher returned an invalid payload")
            keys = self._parse_jwks(payload)
            self._keys = keys
            self._expires_monotonic = time.monotonic() + self._cache_ttl_seconds

    def healthy(self) -> bool:
        try:
            self._refresh()
        except Exception:
            return False
        with self._lock:
            return bool(self._keys and time.monotonic() < self._expires_monotonic)

    def _key_for(self, kid: str) -> Any:
        self._refresh()
        with self._lock:
            key = self._keys.get(kid)
            if key is not None:
                return key
            now = time.monotonic()
            if self._unknown_kid_refresh_in_progress:
                raise AuthenticationUnavailable("could not refresh configured JWKS")
            may_refresh = (
                now - self._last_unknown_kid_refresh_monotonic
                >= self._unknown_kid_refresh_cooldown_seconds
            )
            if may_refresh:
                # Claim this refresh slot before releasing the lock so concurrent
                # attacker-controlled unknown kids cannot trigger parallel fetches.
                self._last_unknown_kid_refresh_monotonic = now
                self._unknown_kid_refresh_in_progress = True
                self._last_unknown_kid_refresh_unavailable = False
            elif self._last_unknown_kid_refresh_unavailable:
                # A refresh already failed inside the cooldown window. Preserve
                # outage semantics for subsequent unknown kids instead of changing
                # the same IdP incident from 503 to a misleading credential 401.
                raise AuthenticationUnavailable("could not refresh configured JWKS")
        if may_refresh:
            try:
                self._refresh(force=True)
            except Exception as exc:
                with self._lock:
                    self._unknown_kid_refresh_in_progress = False
                    self._last_unknown_kid_refresh_unavailable = True
                if isinstance(exc, AuthenticationUnavailable):
                    raise
                raise AuthenticationUnavailable("could not refresh configured JWKS") from exc
            with self._lock:
                self._unknown_kid_refresh_in_progress = False
                self._last_unknown_kid_refresh_unavailable = False
                key = self._keys.get(kid)
            if key is not None:
                return key
        raise AuthenticationError("invalid bearer token")

    def verify(self, token: str) -> dict[str, Any]:
        compact = token.strip()
        if not compact or len(compact.encode("utf-8")) > JWT_MAX_BYTES:
            raise AuthenticationError("invalid bearer token")
        try:
            header = self._jwt.get_unverified_header(compact)
        except Exception as exc:
            raise AuthenticationError("invalid bearer token") from exc
        if header.get("alg") not in _ALLOWED_ALGORITHMS:
            raise AuthenticationError("invalid bearer token")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid.strip():
            raise AuthenticationError("invalid bearer token")
        key = self._key_for(kid.strip())
        try:
            claims = self._jwt.decode(
                compact,
                key=key,
                algorithms=list(_ALLOWED_ALGORITHMS),
                audience=self.audience,
                issuer=self.issuer,
                leeway=JWT_LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception as exc:
            raise AuthenticationError("invalid bearer token") from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("invalid bearer token")
        return dict(claims)

    def authenticate_authorization_header(self, value: str | None) -> dict[str, Any]:
        if value is None:
            raise AuthenticationError("authentication required")
        scheme, separator, token = value.strip().partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip() or " " in token.strip():
            raise AuthenticationError("invalid bearer token")
        return self.verify(token)
