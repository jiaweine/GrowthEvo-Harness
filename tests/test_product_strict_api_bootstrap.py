from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "growthevo" / "web" / "static"


def test_api_bootstrap_cannot_silently_fall_back_to_demo() -> None:
    data_js = (STATIC / "data.js").read_text(encoding="utf-8")
    runtime_ui = (STATIC / "runtime-ui.js").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")

    assert index.index("data.js") < index.index("runtime-ui.js") < index.index("app.js")
    assert "Strict API runtime has not initialized; refusing synthetic fallback" in data_js
    assert "API unavailable; using demo mode" not in data_js
    assert "return demoApi(path,options)" in data_js
    assert "if(useDemo)" in data_js

    assert "api = async function runtimeAwareApi" in runtime_ui
    assert "if (useDemo) return demoApi(path, options);" in runtime_ui
    assert "throw Error(`HTTP ${response.status}:" in runtime_ui
    assert "return demoApi(path, options)" not in runtime_ui
