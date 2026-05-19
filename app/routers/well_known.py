"""
Agent operations well-known router.

Implements /.well-known/agent.json as the control-plane front door for
autonomous clients.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any

from ..core.config import get_settings

router = APIRouter(prefix="", tags=["Agent Discovery"])

settings = get_settings()


def get_agent_first_metadata() -> dict[str, Any]:
    """
    Single source of truth for agent-first bootstrap hints.
    Used by /.well-known/agent.json and GET /v1/discover.
    """
    return {
        "primary_audience": "autonomous_agents",
        "design_principle": "agent_first",
        "bootstrap_sequence": [
            "/.well-known/agent.json",
            "/llm.txt",
            "/mcp/tools.json",
            "/openapi.json",
        ],
        "simulation_and_dependency_truth": "/health/dependencies",
    }


class AgentControlPlaneManifest(BaseModel):
    """Agent operations control-plane manifest."""

    schema_version: str = Field(default="1.0", description="Manifest schema version")
    name: str = Field(description="Control-plane surface name")
    description: str = Field(description="Operational surface this API proves")
    version: str = Field(description="Current version")
    provider: dict = Field(
        default_factory=lambda: {
            "name": "Agent-Native Middleware",
            "website": "https://github.com/PetrefiedThunder/agent-middleware-api",
        }
    )

    capabilities: list[str] = Field(
        default_factory=lambda: [
            "billing",
            "telemetry",
            "agent_communication",
            "ai_decision_making",
            "mcp_tools",
            "awi_automation",
            "sandbox_testing",
            "passkey_auth",
            "dom_bridge",
            "rag_memory",
        ],
        description="List of capability identifiers",
    )

    endpoints: dict = Field(description="API endpoints")

    authentication: dict = Field(
        default_factory=lambda: {
            "type": "api_key",
            "header": "X-API-Key",
        }
    )

    pricing: dict = Field(
        default_factory=lambda: {
            "model": "metered_credits",
            "grants": "operator_configured",
            "credit_conversion": "$0.001 per credit",
        }
    )

    integrations: dict = Field(
        default_factory=lambda: {
            "python_sdk": "pip install b2a-sdk",
            "typescript_sdk": "npm install @b2a/sdk",
            "mcp": True,
            "langgraph": True,
            "crewai": True,
            "autogen": True,
            "llamaindex": True,
        }
    )

    documentation: dict = Field(
        default_factory=lambda: {
            "api_reference": "/docs",
            "openapi": "/openapi.json",
            "llm_readable": "/llm.txt",
            "awi_guide": "/docs/awi-adoption-guide.md",
            "agent_recipes": "/docs/agent-recipes.md",
            "awi_passkey": "/v1/awi/passkey/register",
            "awi_dom_bridge": "/v1/awi/dom/snapshot",
            "awi_rag": "/v1/awi/rag/ingest",
        }
    )

    agent_first: dict[str, Any] = Field(
        default_factory=get_agent_first_metadata,
        description=(
            "How autonomous clients should treat this service: discovery order, "
            "authority for simulation vs real behavior."
        ),
    )


def _build_agent_manifest() -> AgentControlPlaneManifest:
    """Build the agent operations control-plane manifest."""
    return AgentControlPlaneManifest(
        name="agent-middleware-api",
        description=(
            "Agent Ops War Room operational control plane for autonomous agents. "
            "It proves the loop: discover -> authorize -> invoke -> meter -> "
            "receipt -> audit -> verify."
        ),
        version=settings.APP_VERSION,
        endpoints={
            "api_base": "/v1",
            "discovery": "/v1/discover",
            "mcp": "/mcp",
            "awi": "/v1/awi",
            "awi_passkey": "/v1/awi/passkey",
            "awi_dom": "/v1/awi/dom",
            "awi_rag": "/v1/awi/rag",
            "billing": "/v1/billing",
            "telemetry": "/v1/telemetry",
            "comms": "/v1/comms",
            "ai": "/v1/ai",
            "health": "/health",
            "agent_manifest": "/.well-known/agent.json",
            "llm_docs": "/llm.txt",
        },
    )


@router.get(
    "/.well-known/agent.json",
    summary="Agent Operations Manifest",
    description=(
        "Returns the agent operations control-plane manifest. Autonomous clients "
        "use it to find bootstrap surfaces, dependency truth, signed-permit "
        "governance, receipts, and audit verification."
    ),
    responses={
        200: {"description": "Agent operations control-plane manifest"},
    },
)
async def get_agent_json(request: Request):
    """
    Serve the agent.json control-plane manifest.
    """
    manifest = _build_agent_manifest()
    return JSONResponse(
        content=manifest.model_dump(mode="json"),
        media_type="application/json",
    )


@router.get(
    "/.well-known/mcp/tools.json",
    summary="MCP Tools Manifest",
    description="Returns the MCP tools manifest for tool discovery.",
)
async def get_mcp_tools_json():
    """
    Serve the MCP tools manifest.

    This is the standard endpoint MCP clients use to discover
    available tools.
    """
    from .mcp import build_mcp_tools_manifest

    return JSONResponse(content=await build_mcp_tools_manifest())
