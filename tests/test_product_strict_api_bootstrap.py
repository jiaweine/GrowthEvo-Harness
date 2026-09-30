from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "growthevo" / "web" / "static"


def _function_slice(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def test_api_bootstrap_cannot_silently_fall_back_to_demo() -> None:
    data_js = (STATIC / "data.js").read_text(encoding="utf-8")
    runtime_ui = (STATIC / "runtime-ui.js").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")

    # data.js is allowed to serve the explicitly selected Demo workspace only.
    # In API mode it must fail closed until runtime-ui.js installs the strict
    # network implementation; script ordering is therefore part of the contract.
    assert index.index("data.js") < index.index("runtime-ui.js") < index.index("app.js")
    assert "Strict API runtime has not initialized; refusing synthetic fallback" in data_js
    assert "API unavailable; using demo mode" not in data_js
    assert "return demoApi(path,options)" in data_js
    assert "if(useDemo)" in data_js

    # Inspect only runtimeAwareApi itself. An explicit `useDemo` branch is valid;
    # what is forbidden is a catch/error path that silently returns synthetic
    # data after a real API request fails.
    api_impl = _function_slice(
        runtime_ui,
        "api = async function runtimeAwareApi",
        "function setRuntimeStatus",
    )
    assert "if (useDemo) return demoApi(path, options);" in api_impl
    assert api_impl.count("return demoApi(path, options)") == 1
    assert "catch (" not in api_impl
    assert "catch(" not in api_impl
    assert "API unavailable; using demo mode" not in api_impl
    assert "throw Error(`HTTP ${response.status}:" in api_impl
    assert "return await response.json();" in api_impl
