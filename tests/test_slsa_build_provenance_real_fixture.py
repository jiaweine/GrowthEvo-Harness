from __future__ import annotations

from hashlib import sha256
import json
import urllib.request

import pytest

from growthevo.evolution.slsa_build_provenance import (
    GITHUB_ACTIONS_WORKFLOW_BUILD_TYPE_V1,
    SLSABuilderTrust,
    SLSABuildExpectationSpec,
    SLSABuildProvenanceVerifier,
    canonical_external_parameters,
)


pytest.importorskip("pypi_attestations")

FIXTURE_FILENAME = "rez-3.4.0-py3-none-any.whl"
FIXTURE_SHA256 = "d5f45c2bc759a85f0efd91078f541c1c0455577bf4fd42ca23d645013295bf60"
FIXTURE_REPOSITORY = "AcademySoftwareFoundation/rez"
FIXTURE_WORKFLOW = "pypi.yaml"
FIXTURE_REF = "refs/tags/3.4.0"
FIXTURE_COMMIT = "f19dad25ec9cbb6b0e9f53ff2ec5c964b077912a"
FIXTURE_BUILDER = (
    "https://github.com/AcademySoftwareFoundation/rez/.github/workflows/"
    "pypi.yaml@refs/tags/3.4.0"
)
FIXTURE_PUBLISHER = (
    "pypi-trusted-publisher:github:AcademySoftwareFoundation/rez:"
    ".github/workflows/pypi.yaml"
)
FIXTURE_PROVENANCE_URL = (
    "https://pypi.org/integrity/rez/3.4.0/"
    + FIXTURE_FILENAME
    + "/provenance"
)


def _get(url: str, *, accept: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "GrowthEvo-Harness/SLSA-integration-test",
            "Accept": accept,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - pinned HTTPS fixture
        return response.read()


def _wheel_url() -> str:
    document = json.loads(
        _get(
            "https://pypi.org/simple/rez/",
            accept="application/vnd.pypi.simple.v1+json",
        ).decode("utf-8")
    )
    matches = [item["url"] for item in document["files"] if item["filename"] == FIXTURE_FILENAME]
    assert len(matches) == 1
    return matches[0]


def test_real_rez_slsa_build_provenance_verifies_against_l2_root() -> None:
    wheel = _get(_wheel_url(), accept="application/octet-stream")
    assert sha256(wheel).hexdigest() == FIXTURE_SHA256

    provenance = _get(
        FIXTURE_PROVENANCE_URL,
        accept="application/vnd.pypi.integrity.v1+json",
    )
    external = {
        "workflow": {
            "ref": FIXTURE_REF,
            "repository": "https://github.com/AcademySoftwareFoundation/rez",
            "path": ".github/workflows/pypi.yaml",
        }
    }
    spec = SLSABuildExpectationSpec(
        distribution_filename=FIXTURE_FILENAME,
        distribution_sha256=FIXTURE_SHA256,
        expected_repository=FIXTURE_REPOSITORY,
        expected_workflow=FIXTURE_WORKFLOW,
        expected_source_ref=FIXTURE_REF,
        expected_source_commit_sha=FIXTURE_COMMIT,
        expected_external_parameters_json=canonical_external_parameters(external),
        trusted_builders=(
            SLSABuilderTrust(
                publisher_identity=FIXTURE_PUBLISHER,
                builder_id=FIXTURE_BUILDER,
                # GitHub documents ordinary artifact attestations as SLSA Build L2.
                # L3 requires a trusted reusable-workflow architecture and must use
                # a separately assessed root-of-trust entry.
                max_build_level=2,
            ),
        ),
        minimum_build_level=2,
        allowed_build_types=(GITHUB_ACTIONS_WORKFLOW_BUILD_TYPE_V1,),
        offline=True,
    )
    verified = SLSABuildProvenanceVerifier(
        provenance_json=provenance,
        spec=spec,
    ).verify()

    assert verified.distribution_sha256 == FIXTURE_SHA256
    assert verified.publisher_identity == FIXTURE_PUBLISHER
    assert verified.builder_id == FIXTURE_BUILDER
    assert verified.trusted_build_level == 2
    assert verified.build_type == GITHUB_ACTIONS_WORKFLOW_BUILD_TYPE_V1
    assert verified.source_dependency_uri == (
        "git+https://github.com/AcademySoftwareFoundation/rez@refs/tags/3.4.0"
    )
    assert verified.source_commit_sha == FIXTURE_COMMIT
