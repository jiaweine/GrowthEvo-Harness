from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from growthevo.llm.provider_pool import ProviderFailoverClient, ProviderRoute
from test_agent_operating_system import finish, step
from test_product_oidc_auth import _auth, _key, _token, ISSUER, JWKS_URL, AUDIENCE


@pytest.fixture
def authenticated_factory(monkeypatch):
    from growthevo.web import app as web_app, auth as auth_module
    private, jwk = _key("journal-test")
    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("GROWTHEVO_AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("GROWTHEVO_AUTH_JWKS_URL", JWKS_URL)
    monkeypatch.setenv("GROWTHEVO_AUTH_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    monkeypatch.setenv("GROWTHEVO_OPENAI_MODEL", "fixture-model")
    monkeypatch.setattr(auth_module, "OidcJwksAuthenticator", lambda **kwargs: _auth(jwk))
    models = []

    class Model:
        provider_name, model = "fixture", "fixture-model"

        def __init__(self):
            self.contexts = []

        def generate(self, **kwargs):
            raise AssertionError("only async calls expected")

        async def agenerate(self, **kwargs):
            context = json.loads(kwargs["user"])
            self.contexts.append(context)
            count = len(context["previous_steps"])
            if count == 0:
                return step("workspace.read", {"section": "campaigns"})
            if count == 1:
                return step("page.navigate", {"route": "campaignStudio"})
            return finish("界面已打开")

        async def aclose(self):
            pass

    def pool():
        model = Model()
        models.append(model)
        return ProviderFailoverClient([ProviderRoute("fixture", model)])

    monkeypatch.setattr(web_app, "build_provider_pool_from_env", pool)
    alice = {"Authorization": "Bearer " + _token(private, "journal-test", sub="journal-alice")}
    bob = {"Authorization": "Bearer " + _token(private, "journal-test", sub="journal-bob")}
    return web_app.create_app, alice, bob, models


def test_authenticated_execution_never_uses_caller_selected_scopes(authenticated_factory):
    create_app, alice, bob, models = authenticated_factory
    with TestClient(create_app()) as client:
        result = client.post("/api/agent/run", headers=alice, json={"goal": "打开活动设计界面"}).json()
        run_id = result["run_id"]
        assert result["status"] == "awaiting_ui_confirmation"
        assert len(models[0].contexts) == 2
        assert client.get("/api/harness/runs", headers=alice).json()[0]["run_id"] == run_id
        assert client.get("/api/harness/runs", headers=bob).json() == []
        path = f"/api/agent/runs/{run_id}"
        for suffix in ("", "/events"):
            assert client.get(path + suffix, headers=bob).status_code == 404
        for suffix in ("/resume", "/cancel"):
            assert client.post(path + suffix, headers=bob, json={}).status_code == 404
        assert client.post(path + "/ui-confirmation", headers=bob, json={
            "token": result["ui_confirmation_token"], "receipts": [{"step_index": 1, "status": "confirmed"}]
        }).status_code == 404
        assert client.get("/api/harness/runs", headers={**bob, "X-Tenant-Id": "journal-alice"}).json() == []
        assert client.get("/api/harness/runs").status_code == 401
        duplicate = [("Authorization", alice["Authorization"]), ("Authorization", bob["Authorization"])]
        assert client.get("/api/harness/runs", headers=duplicate).status_code == 401
        assert client.post(path + "/cancel", headers=alice).json()["status"] == "cancelled"
        assert "ui_confirmation_token" not in client.get(path, headers=alice).json()
        assert client.post(path + "/resume", headers=alice, json={}).json()["status"] == "cancelled"
        assert len(models[0].contexts) == 2


def test_postgres_api_restores_checkpoint_and_browser_token_after_app_restart(authenticated_factory, monkeypatch):
    url = os.getenv("GROWTHEVO_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("GROWTHEVO_TEST_DATABASE_URL is required for restart recovery")
    create_app, alice, bob, models = authenticated_factory
    monkeypatch.setenv("GROWTHEVO_DATABASE_URL", url)
    with TestClient(create_app()) as before:
        result = before.post("/api/agent/run", headers=alice, json={"goal": "重启后继续打开活动设计界面"}).json()
        run_id = result["run_id"]
        assert result["durability"] == "postgresql"
        assert result["status"] == "awaiting_ui_confirmation"
    with TestClient(create_app()) as after:
        detail = after.get(f"/api/agent/runs/{run_id}", headers=alice).json()
        assert detail["ui_confirmation_token"] == result["ui_confirmation_token"]
        confirmation = after.post(f"/api/agent/runs/{run_id}/ui-confirmation", headers=alice, json={
            "token": detail["ui_confirmation_token"], "receipts": [{"step_index": 1, "status": "confirmed"}]
        })
        assert confirmation.json()["status"] == "ui_confirmed"
        resumed = after.post(f"/api/agent/runs/{run_id}/resume", headers=alice, json={}).json()
        assert resumed["status"] == "completed"
        assert resumed["tool_calls"] == 2
        assert len(models[-1].contexts) == 1
        assert '"browser_confirmation": "confirmed"' in models[-1].contexts[0]["previous_steps"][-1]["feedback"]
        assert after.get(f"/api/agent/runs/{run_id}", headers=bob).status_code == 404
