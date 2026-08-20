"""Test delivery_uncertain replay protection and reconciliation.

This test verifies the core economic-loop requirement from WEDGE.md:
"a genuinely ambiguous post-dispatch outcome becomes a distinct receipted state
rather than a silent redispatch", and that "replay of the same idempotency key
must not cause a second gateway dispatch or a second ledger debit."
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, McpDispatchAttemptModel
from app.services.idempotency import get_idempotency_service
from app.services.mcp_dispatch_attempts import (
    DISPATCH_DISPATCHED,
    get_mcp_dispatch_attempt_service,
)
from app.services.upstream_mcp import UpstreamMcpDeliveryUncertainError
from tests.support.provision import create_tool_permit, provision_agent_wallet
from tests.support.upstream_mcp_executor import UpstreamMcpExecutor


class AmbiguousExecutor(UpstreamMcpExecutor):
    """Executor that raises delivery_uncertain after dispatch checkpoint."""

    def __init__(self) -> None:
        self.dispatch_count = 0
        self.calls: list[dict] = []

    async def call_tool(
        self,
        arguments: dict,
        *,
        invocation_id: str,
        idempotency_key: str | None = None,
        before_dispatch = None,
    ):
        self.calls.append({"arguments": arguments, "idempotency_key": idempotency_key})
        if before_dispatch:
            await before_dispatch()
        self.dispatch_count += 1
        raise UpstreamMcpDeliveryUncertainError()


@pytest.mark.anyio
async def test_replay_after_dispatched_triggers_reconciliation(
    client: AsyncClient,
    clean_database,
) -> None:
    """Replay of a dispatched-but-incomplete attempt reconciles immediately.

    This tests the fix for the scenario where:
    1. First call marks attempt as dispatched
    2. Crash before idempotency.complete()
    3. Reconciler hasn't run yet
    4. Retry with same idempotency key should:
       - NOT raise IdempotencyInProgressError indefinitely
       - NOT redispatch
       - Trigger immediate reconciliation
       - Return the delivery_uncertain receipt
    """
    from app.services.service_registry import get_service_registry

    provisioned = await provision_agent_wallet(client)
    tool_name = "uncertain-replay-test"
    executor = AmbiguousExecutor()
    registry = get_service_registry()
    registry.register_local(
        tool_name,
        lambda **kwargs: None,
        {
            "name": tool_name,
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "creditsPerCall": Decimal("2"),
            "execution_backend": "upstream_mcp",
        },
    )
    registry.register_executor(tool_name, executor)

    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="uncertain-replay-permit",
        )

        # Prepare the idempotency record and dispatch attempt as if a
        # crash happened right after mark_dispatched()
        idem_key = "uncertain-replay-invoke"
        request_payload = {
            "tool": tool_name,
            "arguments": {"test": "value"},
            "wallet_id": provisioned["agent_wallet_id"],
            "permit_id": permit["permit_id"],
        }

        # Create the idempotency record
        idem = get_idempotency_service()
        begun = await idem.begin_with_record(
            wallet_id=provisioned["agent_wallet_id"],
            endpoint="/mcp/invoke",
            idempotency_key=idem_key,
            request_payload=request_payload,
            operation_kind="upstream_mcp",
        )
        assert begun.replay is None

        # Create a dispatched attempt (simulating the crash scenario)
        dispatch = get_mcp_dispatch_attempt_service()
        validation, attempt = await dispatch.authorize_reserve_and_prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            key_id=provisioned["key_id"],
            public_tool_id=tool_name,
            upstream_tool_name=tool_name,
            upstream_origin="https://test.example.com",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("2"),
        )
        assert validation.allowed
        assert attempt is not None

        # Attach charge (simulating successful charge before crash)
        from app.services.agent_money import get_agent_money

        money = get_agent_money()
        charge = await money.charge(
            wallet_id=provisioned["agent_wallet_id"],
            amount_credits=Decimal("2"),
            service_category="api",
            description="Test charge",
            request_path="/test",
            operation_key=begun.record_id,
        )
        await dispatch.attach_charge(
            attempt_id=attempt.attempt_id,
            ledger_entry_id=charge.entry_id,
            credits_charged=Decimal("2"),
        )

        # Mark as dispatched (this is where the "crash" happens)
        attempt = await dispatch.mark_dispatched(attempt.attempt_id)
        assert attempt.state == DISPATCH_DISPATCHED

        # Verify the idempotency record is incomplete
        factory = get_session_factory()
        async with factory() as session:
            record = await session.get(IdempotencyRecordModel, begun.record_id)
            assert record is not None
            assert record.response_json is None

        # Now replay the same idempotency key - this should trigger reconciliation
        replayed = await idem.begin_with_record(
            wallet_id=provisioned["agent_wallet_id"],
            endpoint="/mcp/invoke",
            idempotency_key=idem_key,
            request_payload=request_payload,
            operation_kind="upstream_mcp",
        )

        # Should have replay data now
        assert replayed.replay is not None
        assert replayed.replay.response_json is not None
        response = replayed.replay.response_json

        # Verify it's a delivery_uncertain response
        assert "error" in response or "content" in response
        if "receipt" in response:
            receipt = response["receipt"]
        elif "error" in response and isinstance(response["error"], dict):
            receipt = response["error"].get("data", {}).get("receipt")
        else:
            receipt = response.get("receipt")

        assert receipt is not None
        assert receipt["outcome"] == "delivery_uncertain"
        assert Decimal(str(receipt["credits_charged"])) == Decimal("2")

        # Verify NO redispatch occurred
        assert executor.dispatch_count == 0, "Executor should not have been called"

        # Verify only one debit
        balance_response = await client.get(
            f"/v1/wallets/{provisioned['agent_wallet_id']}/balance",
            headers=provisioned["agent_headers"],
        )
        assert balance_response.status_code == 200
        balance = Decimal(str(balance_response.json()["balance"]))
        # Started with 1000, charged 2, so should be 998
        assert balance == Decimal("998")

    finally:
        registry.unregister_local(tool_name)


@pytest.mark.anyio
async def test_delivery_uncertain_replay_never_redispatches(
    client: AsyncClient,
    clean_database,
) -> None:
    """Replay of a completed delivery_uncertain never redispatches.

    This is the core economic invariant: once a dispatch is ambiguous
    and has been receipted, replay returns the same receipt without
    re-executing the tool.
    """
    from app.services.service_registry import get_service_registry

    provisioned = await provision_agent_wallet(client)
    tool_name = "no-redispatch-test"
    executor = AmbiguousExecutor()
    registry = get_service_registry()
    registry.register_local(
        tool_name,
        lambda **kwargs: None,
        {
            "name": tool_name,
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "creditsPerCall": Decimal("2"),
            "execution_backend": "upstream_mcp",
        },
    )
    registry.register_executor(tool_name, executor)

    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="no-redispatch-permit",
        )

        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {"test": "value"},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "no-redispatch-invoke",
                },
            },
        }

        # First call - should result in delivery_uncertain
        first = await client.post(
            "/mcp/messages", json=body, headers=provisioned["agent_headers"]
        )
        assert first.status_code == 200
        first_data = first.json()
        assert "error" in first_data
        assert first_data["error"]["message"] == "delivery_uncertain"
        first_receipt = first_data["error"]["data"]["receipt"]
        assert first_receipt["outcome"] == "delivery_uncertain"

        # Verify one dispatch occurred
        assert executor.dispatch_count == 1

        # Replay - should return identical receipt without redispatching
        replay = await client.post(
            "/mcp/messages", json=body, headers=provisioned["agent_headers"]
        )
        assert replay.status_code == 200
        replay_data = replay.json()

        # Should be identical
        assert replay_data == first_data

        # Verify NO additional dispatch
        assert executor.dispatch_count == 1, "Should not redispatch on replay"

        # Verify only one debit
        ledger_response = await client.get(
            f"/v1/wallets/{provisioned['agent_wallet_id']}/ledger",
            headers=provisioned["agent_headers"],
        )
        assert ledger_response.status_code == 200
        entries = ledger_response.json()["entries"]
        debits = [e for e in entries if e["action"] == "debit"]
        assert len(debits) == 1, "Should have exactly one debit"

    finally:
        registry.unregister_local(tool_name)
