from __future__ import annotations

from hashlib import sha256
import urllib.request

import pytest

from growthevo.evolution.pypi_provenance import (
    PYPI_ATTESTATIONS_VERSION,
    PYPI_PUBLISH_PREDICATE_V1,
    PyPIPublishProvenanceSpec,
    PyPIPublishProvenanceVerifier,
)


pytest.importorskip("pypi_attestations")

FIXTURE_FILENAME = "pypi_attestations-0.0.30-py3-none-any.whl"
FIXTURE_SHA256 = "b3a9c53f6cb89e5e7b5b70e6cfca97cfc66008c1ed54087355e06e40071cef21"
FIXTURE_SOURCE_COMMIT = "845bfac2f2912912fb2d1ab96775ac75708279c4"
FIXTURE_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/5f/24/"
    "e59078318b5e2bca59be5a21957d70e082e6eb4f478adffe373f3b74daf4/"
    + FIXTURE_FILENAME
)
FIXTURE_PROVENANCE_URL = (
    "https://pypi.org/integrity/pypi-attestations/0.0.30/"
    + FIXTURE_FILENAME
    + "/provenance"
)


def _get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "GrowthEvo-Harness/PEP740-integration-test",
            "Accept": "application/vnd.pypi.integrity.v1+json"
            if url.endswith("/provenance")
            else "application/octet-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - pinned HTTPS fixture
        return response.read()


def test_real_pypi_publish_provenance_verifies_end_to_end() -> None:
    import pypi_attestations

    assert pypi_attestations.__version__ == PYPI_ATTESTATIONS_VERSION

    wheel = _get(FIXTURE_WHEEL_URL)
    assert sha256(wheel).hexdigest() == FIXTURE_SHA256

    provenance = _get(FIXTURE_PROVENANCE_URL)
    spec = PyPIPublishProvenanceSpec(
        distribution_filename=FIXTURE_FILENAME,
        distribution_sha256=FIXTURE_SHA256,
        expected_repository="pypi/pypi-attestations",
        expected_workflow="release.yml",
        expected_source_commit_sha=FIXTURE_SOURCE_COMMIT,
        predicate_type=PYPI_PUBLISH_PREDICATE_V1,
        pypi_attestations_version="0.0.30",
        offline=True,
    )
    verified = PyPIPublishProvenanceVerifier(
        provenance_json=provenance,
        spec=spec,
    ).verify()

    assert verified.distribution_filename == FIXTURE_FILENAME
    assert verified.distribution_sha256 == FIXTURE_SHA256
    assert verified.source_repository_uri == "https://github.com/pypi/pypi-attestations"
    assert verified.source_repository_digest == FIXTURE_SOURCE_COMMIT
    assert verified.build_config_uri.startswith(
        "https://github.com/pypi/pypi-attestations/.github/workflows/release.yml@"
    )
    assert verified.predicate_type == PYPI_PUBLISH_PREDICATE_V1
    assert verified.verified_attestation_count == 1
