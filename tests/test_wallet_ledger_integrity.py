"""Wallet money moves must be decided by the database, not by a stale read.

Each path here read a balance or counter in one statement and wrote it back in
a later one, serialized only by ``SELECT ... FOR UPDATE``. That lock is a
silent no-op on SQLite, and nothing in this repository forbids SQLite in
production, so these are live on a supported configuration.

The interleaves are forced deterministically through an instrumented session
rather than raced, so they cannot pass by scheduling luck. Each test asserts
the interleave actually fired before asserting anything else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from sqlalchemy import select

from app.db.models import LedgerEntryModel, WalletModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from tests.test_trust_helpers import provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _balance(wallet_id: str) -> Decimal:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.balance


async def _debits(wallet_id: str) -> Decimal:
    """Total of the debits actually written to this wallet's ledger."""
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(LedgerEntryModel.amount).where(
                    LedgerEntryModel.wallet_id == wallet_id,  # type: ignore[arg-type]
                    LedgerEntryModel.action == "debit",  # type: ignore[arg-type]
                )
            )
        ).scalars().all()
    return sum((abs(amount) for amount in rows), Decimal("0"))


async def _set_balance(wallet_id: str, amount: Decimal) -> None:
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            wallet = await session.get(WalletModel, wallet_id)
            assert wallet is not None
            wallet.balance = amount
            session.add(wallet)


def _interleaving_factory(real_factory, hook, state, *, fire_on: int = 1):
    """Wrap a session factory so `hook` runs once, mid-transaction.

    Fires after ``fire_on`` statements have been issued on the wrapped session,
    which places it after the balance has been read and before it is written.
    """

    class _Session:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def execute(self, *args, **kwargs):
            state["executes"] = state.get("executes", 0) + 1
            n = state["executes"]
            # Fire *after* the statement returns, so the hook lands once the
            # value has been read but before anything is written back. Firing
            # beforehand would place the concurrent writer ahead of the read,
            # which is not the race. Counting completed reads also keeps the
            # seam identical across the fixed and unfixed code, which differ in
            # how many statements they issue.
            result = await self._inner.execute(*args, **kwargs)
            if n == fire_on and not state.get("fired"):
                state["fired"] = True
                await hook()
            return result

    class _CM:
        def __init__(self, cm):
            self._cm = cm

        async def __aenter__(self):
            return _Session(await self._cm.__aenter__())

        async def __aexit__(self, *exc):
            return await self._cm.__aexit__(*exc)

    return lambda: (lambda: _CM(real_factory()))


@pytest.mark.anyio
async def test_a_concurrent_charge_cannot_vanish_from_the_balance(
    client, clean_database, monkeypatch
):
    """The balance must equal the opening balance less every debit recorded.

    ``charge`` read ``wallet.balance``, and several statements later wrote back
    ``balance - charge_amount`` computed from that read. The row lock between
    them does nothing on SQLite, so a charge committing in between is
    overwritten: the ledger records the debit, the balance never reflects it,
    and that request was served for free. Conservation — balance equals opening
    balance minus the debits on the books — is the invariant that catches it,
    and it is the one the ledger's own credibility rests on.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    # Exactly enough for one charge, not two.
    await _set_balance(wallet_id, Decimal("10"))

    money = get_agent_money()
    import app.services.billing_engine as billing_module

    real_factory = get_session_factory()
    state: dict = {}

    async def _concurrent_charge() -> None:
        # A second charge commits in full while the first is mid-transaction.
        monkeypatch.setattr(
            billing_module, "get_session_factory", lambda: real_factory, raising=False
        )
        state["second"] = await money.charge(
            wallet_id=wallet_id,
            service_category=ServiceCategory.AGENT_COMMS,
            units=Decimal("1"),
            request_path="/concurrent-b",
        )

    monkeypatch.setattr(
        money._billing_engine,
        "_session_factory",
        _interleaving_factory(real_factory, _concurrent_charge, state, fire_on=1),
    )

    state["first"] = await money.charge(
        wallet_id=wallet_id,
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path="/concurrent-a",
    )

    assert state.get("fired"), "the interleave never ran — the test proved nothing"
    # Whatever mix of success and refusal the two charges produced, the balance
    # must account for exactly the debits the ledger actually recorded.
    assert await _balance(wallet_id) == Decimal("10") - await _debits(wallet_id)
    # And it may never go negative.
    assert await _balance(wallet_id) >= Decimal("0")


@pytest.mark.anyio
async def test_reclaiming_a_child_twice_cannot_mint_credits(
    client, clean_database, monkeypatch
):
    """A child's balance may be reclaimed to its parent exactly once.

    ``reclaim_child_wallet`` read ``child.balance``, zeroed the child, and
    credited the parent by the amount it had read. Both halves were protected
    only by row locks. Two concurrent reclaims of the same child therefore each
    credited the parent the full balance — the parent gained twice what the
    child ever held, and the extra credits were created from nothing.
    """
    money = get_agent_money()
    # Only agent (or child) wallets may spawn children.
    provisioned = await provision_agent_wallet(client)
    parent_id = provisioned["agent_wallet_id"]
    await _set_balance(parent_id, Decimal("100"))
    child = await money.create_child_wallet(
        parent_wallet_id=parent_id,
        child_agent_id="reclaim-integrity-child",
        budget_credits=Decimal("40"),
        max_spend=Decimal("40"),
        task_description="reclaim-integrity",
    )
    child_id = child.wallet_id

    parent_before = await _balance(parent_id)
    child_before = await _balance(child_id)
    assert child_before == Decimal("40")

    import app.services.wallet_engine as wallet_module  # noqa: F401

    real_factory = get_session_factory()
    state: dict = {}

    async def _concurrent_reclaim() -> None:
        monkeypatch.setattr(
            money._wallet_engine, "_session_factory", lambda: real_factory, raising=False
        )
        try:
            state["second"] = await money.reclaim_child_wallet(child_id)
        except Exception as exc:  # a refusal is a correct outcome here
            state["second"] = exc

    monkeypatch.setattr(
        money._wallet_engine,
        "_session_factory",
        _interleaving_factory(real_factory, _concurrent_reclaim, state, fire_on=1),
    )

    try:
        state["first"] = await money.reclaim_child_wallet(child_id)
    except Exception as exc:
        state["first"] = exc

    assert state.get("fired"), "the interleave never ran — the test proved nothing"
    # The parent may gain exactly what the child held, never twice.
    assert await _balance(parent_id) == parent_before + child_before
    assert await _balance(child_id) == Decimal("0")
