from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_web_container_uses_locked_runtime_without_local_package_build() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "--constraint constraints/web-container-py313.txt" in dockerfile
    assert "fastapi==0.141.1 uvicorn==0.54.0" in dockerfile
    assert "'.[web]'" not in dockerfile
    assert 'CMD ["python", "-m", "growthevo.web.cli"]' in dockerfile
    assert "COPY pyproject.toml" not in dockerfile
