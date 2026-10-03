from __future__ import annotations

import pytest

from growthevo.web.runtime import RuntimeSettings


def test_runtime_environment_label_is_header_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_ENV", "Prod_US-East.1")
    assert RuntimeSettings.from_env().environment == "prod_us-east.1"

    for value in (
        "prod\nX-Injected: yes",
        "prod/us-east",
        "prod us-east",
        "x" * 65,
    ):
        monkeypatch.setenv("GROWTHEVO_ENV", value)
        with pytest.raises(ValueError, match="invalid GROWTHEVO_ENV"):
            RuntimeSettings.from_env()
