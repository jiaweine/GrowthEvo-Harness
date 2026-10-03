from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

jwt = pytest.importorskip("jwt")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

from growthevo.web import auth as auth_module
from growthevo.web.auth import (
    AuthConfigurationError,
    AuthenticationError,
    AuthenticationUnavailable,
    OidcJwksAuthenticator,
)

ISSUER = "https://issuer.example.test/growthevo"
JWKS_URL = "https://identity.example.test/.well-known/jwks.json"
AUDIENCE = "growthevo-product"


def _key(kid: str):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return private_key, jwk


def _claims(*, issuer: str = ISSUER, audience: str = AUDIENCE, expires_in: int = 300):
    now = datetime.now(timezone.utc)
    return {
        "iss": issuer,
        "aud": audience,
        "sub": "user-ci-123",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }


def _token(private_key, kid: str, **claim_overrides):
    claims = _claims()
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def _auth(jwk, *, fetcher=None):
    return OidcJwksAuthenticator(
        issuer=ISSUER,
        jwks_url=JWKS_URL,
        audience=AUDIENCE,
        require_https=True,
        fetcher=fetcher or (lambda _: {"keys": [jwk]}),
    )


def test_valid_rs256_bearer_is_verified() -> None:
    private_key, jwk = _key("primary")
    auth = _auth(jwk)

    claims = auth.authenticate_authorization_header(
        f"Bearer {_token(private_key, 'primary')}"
    )

    assert claims["sub"] == "user-ci-123"
    assert claims["iss"] == ISSUER
    assert claims["aud"] == AUDIENCE
    assert auth.healthy() is True


@pytest.mark.parametrize(
    ("token_factory", "expected"),
    [
        (lambda key: _token(key, "primary", aud="wrong-audience"), "audience"),
        (lambda key: _token(key, "primary", iss="https://wrong.example.test"), "issuer"),
        (lambda key: _token(key, "primary", exp=int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())), "expired"),
    ],
)
def test_invalid_registered_claims_fail_closed(token_factory, expected: str) -> None:
    private_key, jwk = _key("primary")
    auth = _auth(jwk)

    with pytest.raises(AuthenticationError, match="invalid bearer token"):
        auth.verify(token_factory(private_key))

    assert expected


def test_algorithm_confusion_is_rejected_before_key_use() -> None:
    _, jwk = _key("primary")
    auth = _auth(jwk)
    hs_token = jwt.encode(
        _claims(),
        "not-an-rsa-private-key-and-never-treated-as-one",
        algorithm="HS256",
        headers={"kid": "primary"},
    )

    with pytest.raises(AuthenticationError, match="invalid bearer token"):
        auth.verify(hs_token)


def test_unknown_kid_refreshes_once_then_rejects() -> None:
    private_key, jwk = _key("primary")
    calls: list[str] = []

    def fetcher(url: str):
        calls.append(url)
        return {"keys": [jwk]}

    auth = _auth(jwk, fetcher=fetcher)
    assert len(calls) == 1

    with pytest.raises(AuthenticationError, match="invalid bearer token"):
        auth.verify(_token(private_key, "unknown-kid"))

    assert calls == [JWKS_URL, JWKS_URL]


def test_repeated_unknown_kid_is_rate_limited_within_refresh_cooldown() -> None:
    private_key, jwk = _key("primary")
    calls: list[str] = []

    def fetcher(url: str):
        calls.append(url)
        return {"keys": [jwk]}

    auth = _auth(jwk, fetcher=fetcher)
    for kid in ("unknown-one", "unknown-two", "unknown-one"):
        with pytest.raises(AuthenticationError, match="invalid bearer token"):
            auth.verify(_token(private_key, kid))

    # One bootstrap plus one forced rotation refresh. Further attacker-controlled
    # unknown key ids inside the cooldown do not create additional IdP traffic.
    assert calls == [JWKS_URL, JWKS_URL]


def test_failed_unknown_kid_refresh_stays_unavailable_during_cooldown() -> None:
    private_key, jwk = _key("primary")
    calls: list[str] = []

    def fetcher(url: str):
        calls.append(url)
        if len(calls) == 1:
            return {"keys": [jwk]}
        raise AuthenticationUnavailable("identity provider offline")

    auth = _auth(jwk, fetcher=fetcher)
    for kid in ("unknown-one", "unknown-two"):
        with pytest.raises(AuthenticationUnavailable):
            auth.verify(_token(private_key, kid))

    # Bootstrap plus one failed forced refresh. The second request preserves 503
    # semantics without creating another outbound request during the cooldown.
    assert calls == [JWKS_URL, JWKS_URL]


def test_malformed_rotation_jwks_is_treated_as_runtime_unavailability() -> None:
    private_key, jwk = _key("primary")
    calls = 0

    def fetcher(_: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"keys": [jwk]}
        return {"keys": "not-a-list"}

    auth = _auth(jwk, fetcher=fetcher)
    with pytest.raises(AuthenticationUnavailable):
        auth.verify(_token(private_key, "unknown-kid"))


def test_unknown_kid_can_succeed_after_normal_key_rotation() -> None:
    _, old_jwk = _key("old")
    new_private_key, new_jwk = _key("new")
    calls = 0

    def fetcher(_: str):
        nonlocal calls
        calls += 1
        return {"keys": [old_jwk]} if calls == 1 else {"keys": [new_jwk]}

    auth = _auth(old_jwk, fetcher=fetcher)
    claims = auth.verify(_token(new_private_key, "new"))

    assert claims["sub"] == "user-ci-123"
    assert calls == 2


def test_jwks_redirect_is_rejected_even_when_redirect_target_is_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, jwk = _key("primary")

    class RedirectedResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def geturl(self) -> str:
            return "https://attacker.example.test/jwks.json"

        def read(self, _: int) -> bytes:
            return json.dumps({"keys": [jwk]}).encode("utf-8")

    monkeypatch.setattr(
        auth_module,
        "urlopen",
        lambda request, timeout: RedirectedResponse(),
    )

    with pytest.raises(AuthConfigurationError, match="must not redirect"):
        OidcJwksAuthenticator(
            issuer=ISSUER,
            jwks_url=JWKS_URL,
            audience=AUDIENCE,
            require_https=True,
        )


def test_malformed_authorization_header_is_rejected() -> None:
    _, jwk = _key("primary")
    auth = _auth(jwk)

    for value in (None, "", "Basic abc", "Bearer", "Bearer a b"):
        with pytest.raises(AuthenticationError):
            auth.authenticate_authorization_header(value)


def test_production_identity_urls_must_use_https() -> None:
    _, jwk = _key("primary")

    with pytest.raises(AuthConfigurationError, match="must use https"):
        OidcJwksAuthenticator(
            issuer="http://issuer.example.test",
            jwks_url=JWKS_URL,
            audience=AUDIENCE,
            require_https=True,
            fetcher=lambda _: {"keys": [jwk]},
        )

    with pytest.raises(AuthConfigurationError, match="must use https"):
        OidcJwksAuthenticator(
            issuer=ISSUER,
            jwks_url="http://identity.example.test/jwks.json",
            audience=AUDIENCE,
            require_https=True,
            fetcher=lambda _: {"keys": [jwk]},
        )


def test_duplicate_jwks_key_ids_are_rejected() -> None:
    _, jwk = _key("duplicate")

    with pytest.raises(AuthConfigurationError, match="duplicate key ids"):
        OidcJwksAuthenticator(
            issuer=ISSUER,
            jwks_url=JWKS_URL,
            audience=AUDIENCE,
            require_https=True,
            fetcher=lambda _: {"keys": [jwk, dict(jwk)]},
        )
