"""Phase 3: production-like deploy posture + railway.json hygiene.

Default conftest stays permissive for unit speed. This module (and the CI
``production_trust`` job) explicitly engages production trust flags.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.trust_mode import (
    describe_permissive_trust_mode,
    validate_trust_mode_config,
)
from app.main import app
from app.services.mcp_phase9_tools import (
    DEFAULT_MCP_STUB_SERVICE_IDS,
    PROOF_SURFACE_MCP_STUB_IDS,
    sync_proof_surface_mcp_registration,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RAILWAY_JSON = REPO_ROOT / "railway.json"

# Dummy non-secret material so production-like validation can pass without
# loading a real signing key into the test process.
_TEST_SIGNING_PRIVATE_KEY_B64 = "dGVzdC1zaWduaW5nLWtleS1ub3QtZm9yLXByb2Q="


@pytest.fixture
def production_trust_flags(monkeypatch):
    """Engage the production trust flag set without flipping the whole suite."""
    import app.main as main_mod
    import app.routers.discover as discover_mod
    import app.routers.well_known as well_known_mod

    monkeypatch.setenv("TRUST_MODE_ENABLED", "true")
    monkeypatch.setenv("ALLOW_LEGACY_UNPERMITTED_MCP", "false")
    monkeypatch.setenv("ENABLE_PROOF_SURFACES", "false")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("WEBAUTHN_ALLOW_MOCK", "false")
    monkeypatch.setenv("TRUST_SIGNING_PRIVATE_KEY_B64", _TEST_SIGNING_PRIVATE_KEY_B64)
    monkeypatch.setenv(
        "PUBLIC_URL", "https://api-service-production-433c.up.railway.app"
    )
    get_settings.cache_clear()
    cfg = get_settings()
    assert cfg.TRUST_MODE_ENABLED is True
    assert cfg.ALLOW_LEGACY_UNPERMITTED_MCP is False
    assert cfg.ENABLE_PROOF_SURFACES is False
    monkeypatch.setattr(main_mod, "settings", cfg)
    monkeypatch.setattr(discover_mod, "settings", cfg)
    monkeypatch.setattr(well_known_mod, "settings", cfg)
    sync_proof_surface_mcp_registration()
    yield cfg
    get_settings.cache_clear()
    restored = get_settings()
    monkeypatch.setattr(main_mod, "settings", restored)
    monkeypatch.setattr(discover_mod, "settings", restored)
    monkeypatch.setattr(well_known_mod, "settings", restored)
    sync_proof_surface_mcp_registration()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.production_trust
def test_railway_json_has_no_change_me_api_key_default():
    raw = RAILWAY_JSON.read_text(encoding="utf-8")
    assert "change-me" not in raw.lower()
    data = json.loads(raw)
    variables = data.get("variables") or {}
    assert "VALID_API_KEYS" not in variables
    assert variables.get("STATE_BACKEND") == "postgres"
    assert variables.get("PUBLIC_URL", "").startswith("https://")
    assert str(variables.get("ENABLE_PROOF_SURFACES", "")).lower() == "false"
    assert data.get("build", {}).get("builder") == "DOCKERFILE"


@pytest.mark.production_trust
def test_production_trust_flags_are_strict(production_trust_flags):
    cfg = production_trust_flags
    validate_trust_mode_config(
        environment=cfg.ENVIRONMENT,
        trust_mode_enabled=cfg.TRUST_MODE_ENABLED,
        signing_private_key_b64=cfg.TRUST_SIGNING_PRIVATE_KEY_B64,
        allow_legacy_unpermitted_mcp=cfg.ALLOW_LEGACY_UNPERMITTED_MCP,
        debug=cfg.DEBUG,
        webauthn_allow_mock=cfg.WEBAUTHN_ALLOW_MOCK,
        enable_proof_surfaces=cfg.ENABLE_PROOF_SURFACES,
    )
    assert (
        describe_permissive_trust_mode(
            trust_mode_enabled=cfg.TRUST_MODE_ENABLED,
            allow_legacy_unpermitted_mcp=cfg.ALLOW_LEGACY_UNPERMITTED_MCP,
        )
        is None
    )


@pytest.mark.production_trust
@pytest.mark.anyio
async def test_agent_json_reports_proof_surfaces_off(client, production_trust_flags):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    body = resp.json()
    agent_first = body.get("agent_first") or {}
    assert agent_first.get("proof_surfaces_enabled") is False
    # Catalog may still list proof ids, but they must be marked unmounted.
    for entry in body.get("proof_surfaces") or []:
        assert entry.get("mounted") is False


@pytest.mark.production_trust
@pytest.mark.anyio
async def test_tools_json_omits_proof_stubs_under_prod_flags(
    client, production_trust_flags
):
    resp = await client.get("/mcp/tools.json")
    assert resp.status_code == 200
    names = {tool["name"] for tool in resp.json()["tools"]}
    assert names.isdisjoint(PROOF_SURFACE_MCP_STUB_IDS)
    assert names.isdisjoint(DEFAULT_MCP_STUB_SERVICE_IDS)
    assert not any(name.startswith("awi_") for name in names)


@pytest.mark.production_trust
@pytest.mark.anyio
async def test_health_dependencies_reports_proof_surfaces_off(
    client, production_trust_flags
):
    resp = await client.get("/health/dependencies")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("enable_proof_surfaces") is False
