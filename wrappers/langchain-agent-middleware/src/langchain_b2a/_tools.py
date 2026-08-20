"""Internal tool implementations."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from langchain_core.tools import StructuredTool

from b2a_sdk.models import PermitRequest

from .client import B2AClient


def create_mcp_tool(
    client: B2AClient,
    *,
    wallet_id: str,
    permit_budget: Decimal = Decimal("100"),
    permit_ttl_minutes: int = 30,
) -> StructuredTool:
    """Create a LangChain tool that calls MCP endpoints via governed permit→invoke→receipt flow.

    Args:
        client: AgentMiddlewareClient instance
        wallet_id: Wallet ID for billing
        permit_budget: Maximum credits per permit (default 100)
        permit_ttl_minutes: Permit lifetime in minutes (default 30)
    """

    async def call_mcp(
        tool_name: str,
        idempotency_key: str,
        arguments: dict[str, Any] | None = None,
        permit_idempotency_key: str | None = None,
    ) -> str:
        """Call an MCP tool via permit→invoke→receipt flow.

        Args:
            tool_name: Name of the MCP tool to call
            idempotency_key: Caller-supplied idempotency key for invoke_tool (required)
            arguments: Arguments to pass to the tool
            permit_idempotency_key: Idempotency key for permit creation (defaults to f"permit-{idempotency_key}")
        """
        if arguments is None:
            arguments = {}
        if not idempotency_key or not idempotency_key.strip():
            raise ValueError("idempotency_key is required and must not be blank")

        if permit_idempotency_key is None:
            permit_idempotency_key = f"permit-{idempotency_key}"

        request = PermitRequest(
            issuer_wallet_id=wallet_id,
            subject_wallet_id=wallet_id,
            max_credits=permit_budget,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=permit_ttl_minutes),
            allowed_tools=[tool_name],
            scopes=[f"tool:{tool_name}:invoke", "billing:charge"],
        )

        permit = await client.create_permit(request, idempotency_key=permit_idempotency_key)

        result = await client.invoke_tool(
            tool_name,
            arguments,
            wallet_id=wallet_id,
            permit_id=permit.permit_id,
            idempotency_key=idempotency_key,
        )

        return str(
            {
                "content": result.content,
                "structured_content": result.structured_content,
                "receipt_id": result.receipt.receipt_id,
                "credits_charged": str(result.receipt.credits_charged),
                "signature": result.receipt.signature,
            }
        )

    return StructuredTool.from_function(
        func=call_mcp,
        name="mcp_tool_call",
        description="Call a Model Context Protocol (MCP) tool from Agent Middleware API. "
        "Use this to access billable services like data indexing, content generation, etc. "
        "Returns signed receipts for all invocations.",
        args_schema={
            "tool_name": str,
            "idempotency_key": str,
            "arguments": dict,
            "permit_idempotency_key": str,
        },
    )


def create_wallet_tool(client: B2AClient, *, wallet_id: str) -> StructuredTool:
    """Create a LangChain tool for wallet operations."""

    async def get_balance() -> str:
        """Get current wallet balance."""
        balance = await client.get_balance(wallet_id)
        return f"Balance: {balance} credits"

    return StructuredTool.from_function(
        func=get_balance,
        name="wallet_balance",
        description="Get the current wallet balance from Agent Middleware API.",
    )


def create_langgraph_tools(
    client: B2AClient,
    *,
    wallet_id: str,
    permit_budget: Decimal = Decimal("100"),
    permit_ttl_minutes: int = 30,
) -> list[Callable]:
    """Get tools formatted for LangGraph ReAct agents."""
    return [
        create_mcp_tool(
            client,
            wallet_id=wallet_id,
            permit_budget=permit_budget,
            permit_ttl_minutes=permit_ttl_minutes,
        ),
        create_wallet_tool(client, wallet_id=wallet_id),
    ]
