from __future__ import annotations

from importlib.metadata import version
from inspect import signature

import pytest


sigstore = pytest.importorskip("sigstore")


def test_sigstore_sdk_version_is_exactly_pinned() -> None:
    assert version("sigstore") == "4.5.0"


def test_public_dsse_verification_api_contract_exists() -> None:
    from sigstore.models import Bundle
    from sigstore.verify import Verifier
    from sigstore.verify.policy import Identity

    from_json = signature(Bundle.from_json)
    assert "raw" in from_json.parameters

    production = signature(Verifier.production)
    assert "offline" in production.parameters
    assert production.parameters["offline"].kind.name == "KEYWORD_ONLY"

    verify_dsse = signature(Verifier.verify_dsse)
    assert list(verify_dsse.parameters)[:3] == ["self", "bundle", "policy"]

    identity = signature(Identity)
    assert "identity" in identity.parameters
    assert "issuer" in identity.parameters


def test_offline_production_verifier_and_identity_construct_without_network() -> None:
    from sigstore.verify import Verifier
    from sigstore.verify.policy import Identity

    verifier = Verifier.production(offline=True)
    policy = Identity(
        identity="https://github.com/example/repo/.github/workflows/release.yml@refs/tags/v1",
        issuer="https://token.actions.githubusercontent.com",
    )
    assert verifier is not None
    assert policy is not None


def test_real_bundle_parser_rejects_malformed_dsse_bundle() -> None:
    from sigstore.models import Bundle

    malformed = """{
      "mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json",
      "verificationMaterial":{},
      "dsseEnvelope":{
        "payload":"e30=",
        "payloadType":"application/vnd.in-toto+json",
        "signatures":[{"sig":"c2ln"}]
      }
    }"""
    with pytest.raises(Exception):
        Bundle.from_json(malformed)
