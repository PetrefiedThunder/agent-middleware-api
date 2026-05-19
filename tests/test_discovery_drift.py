import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import mcp_phase9_tools
from app.services.mcp_phase9_tools import MCP_PHASE9_TOOLS
from app.services.service_registry import get_service_registry


_DEFAULT_MCP_TOOL_IDS = {
    "data-indexer",
    "content-generator",
    "telemetry-processor",
    "semantic-search",
}


def _clear_builtin_mcp_tools_for_lazy_start():
    registry = get_service_registry()
    for tool in MCP_PHASE9_TOOLS:
        registry.unregister_local(tool["service_id"])
    for tool_id in _DEFAULT_MCP_TOOL_IDS:
        registry.unregister_local(tool_id)
    mcp_phase9_tools._registered = False
    mcp_phase9_tools._default_services_registered = False


def _assert_phase9_tool_available(tools):
    assert {tool["name"] for tool in tools} >= {"awi_passkey_challenge"}


def _tools_by_name(tools):
    return {tool["name"]: tool for tool in tools}


def _without_generated_at(manifest):
    return {key: value for key, value in manifest.items() if key != "generated_at"}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_agent_manifest_points_to_canonical_control_plane_surfaces(client):
    response = await client.get("/.well-known/agent.json")

    assert response.status_code == 200
    data = response.json()
    endpoints = data["endpoints"]
    agent_first = data["agent_first"]

    assert endpoints["billing"] == "/v1/billing"
    assert endpoints["mcp"] == "/mcp"
    assert endpoints["health"] == "/health"
    assert endpoints["agent_manifest"] == "/.well-known/agent.json"
    assert endpoints["llm_docs"] == "/llm.txt"
    assert "/mcp/tools.json" in agent_first["bootstrap_sequence"]
    assert agent_first["simulation_and_dependency_truth"] == "/health/dependencies"


@pytest.mark.anyio
async def test_discover_and_agent_manifest_share_agent_first_contract(client):
    agent_response = await client.get("/.well-known/agent.json")
    discover_response = await client.get("/v1/discover")

    assert agent_response.status_code == 200
    assert discover_response.status_code == 200
    agent_manifest = agent_response.json()
    discover_manifest = discover_response.json()

    assert agent_manifest["agent_first"] == discover_manifest["agent_first"]
    assert "control plane" in agent_manifest["description"].lower()
    assert "control plane" in discover_manifest["description"].lower()
    assert (
        "discover -> authorize -> invoke -> meter -> receipt -> audit -> verify"
        in discover_manifest["description"].lower()
    )


@pytest.mark.anyio
async def test_discovery_front_door_does_not_market_free_unlimited_tiers(client):
    discover_response = await client.get("/v1/discover")
    agent_response = await client.get("/.well-known/agent.json")

    assert discover_response.status_code == 200
    assert agent_response.status_code == 200
    combined = f"{discover_response.text}\n{agent_response.text}".lower()

    assert "unlimited credits" not in combined
    assert "unlimited everything" not in combined
    assert "free tier" not in combined


@pytest.mark.anyio
async def test_public_discovery_copy_avoids_directory_marketplace_centering(client):
    root_response = await client.get("/")
    openapi_response = await client.get("/openapi.json")

    assert root_response.status_code == 200
    assert openapi_response.status_code == 200
    reviewed_copy = f"{root_response.text}\n{openapi_response.text}".lower()

    stale_phrases = [
        "awi phase 9",
        "awi_phase9",
        "crawl directories",
        "inbound discovery traffic",
        "network effects engine",
        "go-to-market engine",
        "infiltrate",
        "agent directories",
        "external agent directories",
        "plugin stores",
        "centralized agent registries",
    ]
    for phrase in stale_phrases:
        assert phrase not in reviewed_copy


@pytest.mark.anyio
async def test_openapi_contains_core_control_plane_routes(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/mcp/messages" in paths
    assert "/mcp/tools/{service_id}/invoke" in paths
    assert "/v1/billing/charge" in paths
    assert "/v1/audit/events" in paths
    assert "/v1/planner/optimize" in paths


@pytest.mark.anyio
async def test_mcp_manifest_tools_include_pricing_and_simulation_truth(client):
    response = await client.get("/mcp/tools.json")

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert tools
    for tool in tools:
        annotations = tool["annotations"]
        assert "creditsPerCall" in annotations
        assert "unitName" in annotations
        assert "simulation" in annotations
        assert "integrationStatus" in annotations


@pytest.mark.anyio
async def test_well_known_mcp_manifest_matches_canonical_mcp_manifest(client):
    _clear_builtin_mcp_tools_for_lazy_start()

    well_known_response = await client.get("/.well-known/mcp/tools.json")
    canonical_response = await client.get("/mcp/tools.json")

    assert well_known_response.status_code == 200
    assert canonical_response.status_code == 200
    well_known = well_known_response.json()
    canonical = canonical_response.json()

    assert _without_generated_at(well_known) == _without_generated_at(canonical)

    well_known_tools = _tools_by_name(well_known["tools"])
    assert "awi_passkey_challenge" in well_known_tools

    annotations = well_known_tools["awi_passkey_challenge"]["annotations"]
    assert annotations["creditsPerCall"] == 1.0
    assert annotations["unitName"] == "challenge"
    assert annotations["category"] == "agent_comms"
    assert annotations["simulation"] is True
    assert annotations["integrationStatus"] == "simulated"
    assert annotations["runtimeService"] == "agent_comms"


@pytest.mark.anyio
async def test_prefixed_well_known_mcp_manifest_is_not_a_discovery_route(client):
    response = await client.get("/mcp/.well-known/mcp/tools.json")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_mcp_tools_endpoint_lazily_registers_local_tools(client):
    _clear_builtin_mcp_tools_for_lazy_start()

    response = await client.get("/mcp/tools")

    assert response.status_code == 200
    _assert_phase9_tool_available(response.json()["tools"])


@pytest.mark.anyio
async def test_mcp_messages_tools_list_lazily_registers_local_tools(client):
    _clear_builtin_mcp_tools_for_lazy_start()

    response = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": "lazy-list",
            "method": "tools/list",
            "params": {},
        },
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "lazy-list"
    _assert_phase9_tool_available(payload["result"]["tools"])


@pytest.mark.anyio
async def test_mcp_get_tool_lazily_registers_local_tools(client):
    _clear_builtin_mcp_tools_for_lazy_start()

    response = await client.get("/mcp/tools/awi_passkey_challenge")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "awi_passkey_challenge"
    assert data["annotations"]["creditsPerCall"] == 1.0
