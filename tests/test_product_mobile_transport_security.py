from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mobile_api_fails_closed_without_secure_production_endpoint() -> None:
    source = (ROOT / "apps" / "mobile" / "src" / "api.ts").read_text(encoding="utf-8")
    readme = (ROOT / "apps" / "mobile" / "README.md").read_text(encoding="utf-8")

    assert "declare const __DEV__: boolean;" in source
    assert "EXPO_PUBLIC_GROWTHEVO_API is required outside development" in source
    assert "production mobile builds require an HTTPS GrowthEvo API" in source
    assert "return __DEV__ && !configuredBase?.trim();" in source
    assert "if (!__DEV__ && parsed.protocol !== 'https:')" in source
    assert "Cleartext HTTP is accepted only" in readme
    assert "Production builds require `EXPO_PUBLIC_GROWTHEVO_API`" in readme
