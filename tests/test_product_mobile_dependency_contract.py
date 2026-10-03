from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / "apps" / "mobile"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_mobile_root_identity_stays_on_first_product_version() -> None:
    package = _json(MOBILE / "package.json")
    lock = _json(MOBILE / "package-lock.json")

    assert package["name"] == "growthevo-mobile"
    assert package["version"] == "1.0.0"
    assert lock["name"] == package["name"]
    assert lock["version"] == "1.0.0"
    assert lock["packages"][""]["name"] == package["name"]
    assert lock["packages"][""]["version"] == "1.0.0"


def test_mobile_manifest_stays_on_expo_sdk_57_compatibility_line() -> None:
    package = _json(MOBILE / "package.json")
    dependencies = package["dependencies"]
    dev_dependencies = package["devDependencies"]

    assert dependencies["expo"].startswith("~57.")
    assert dependencies["react"] == "19.2.3"
    assert dependencies["react-native"].startswith("0.86.")
    assert dev_dependencies["@types/react"].startswith("~19.2.")
    assert dev_dependencies["typescript"].startswith("~6.0.")


def test_dependabot_does_not_cross_expo_sdk_57_major_boundaries() -> None:
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    for dependency, boundary in (
        ("react", ">=19.3.0"),
        ("@types/react", ">=19.3.0"),
        ("react-native", ">=0.87.0"),
        ("typescript", ">=7.0.0"),
    ):
        assert f'dependency-name: "{dependency}"' in dependabot
        assert f'- "{boundary}"' in dependabot
