from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from httpx import ASGITransport, AsyncClient

from app import main as app_main
from app.core import auth as auth_module
from app.main import app
from app.core.config import get_settings
from app.db import database as database_module
from app.routers import discover as discover_router
from app.routers import mcp as mcp_router
from app.routers import well_known as well_known_router
from app.services.signing_keys import get_signing_key_service
from scripts.agent_ops_war_room_demo import (
    ALLOWED_TOOL,
    DENIED_TOOL,
    run_in_process,
    run_war_room,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def strict_trust_mode(monkeypatch):
    raw_private_key = Ed25519PrivateKey.generate().private_bytes(
        Encoding.Raw,
        PrivateFormat.Raw,
        NoEncryption(),
    )
    monkeypatch.setattr(mcp_router.settings, "TRUST_MODE_ENABLED", True)
    monkeypatch.setattr(mcp_router.settings, "ALLOW_LEGACY_UNPERMITTED_MCP", False)
    monkeypatch.setattr(
        mcp_router.settings,
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(raw_private_key).decode(),
    )
    signing_keys = get_signing_key_service()
    signing_keys._private_key = None


@pytest.mark.anyio
async def test_agent_ops_war_room_demo_proves_control_plane_loop(
    client,
    clean_database,
    strict_trust_mode,
):
    result = await run_war_room(
        client=client,
        bootstrap_api_key="test-key",
        emit=False,
    )

    assert result["status"] == "pass"
    assert result["discovery"]["bootstrap_tools_seen"] >= 0
    assert result["discovery"]["registered_tools_seen"] >= 2
    assert result["discovery"]["war_room_tools_discoverable"] is True
    assert result["discovery"]["war_room_tool_names"] == [
        ALLOWED_TOOL,
        DENIED_TOOL,
    ]
    assert result["agent"]["wallet_id"].startswith("agt-")
    assert result["permit"]["permit_id"].startswith("permit-")
    assert result["invoke"]["receipt"]["outcome"] == "success"
    assert result["replay"]["same_receipt"] is True
    assert result["ledger"]["matching_debits"] == 1
    assert result["self_inspection"]["permits"] >= 1
    assert result["self_inspection"]["receipts"] >= 1
    assert result["self_inspection"]["audit_events"] >= 1
    assert result["audit"]["chain"]["valid"] is True
    assert result["denial"]["reason"] == "permit_tool_not_allowed"
    assert result["denial"]["receipt"]["outcome"] == "denied"
    assert result["denial"]["receipt"]["tool"] == DENIED_TOOL
    assert result["denial"]["receipt"]["ledger_entry_id"] is None
    assert result["denial"]["receipt"]["credits_charged"] == "0"
    assert result["denial"]["receipt"]["wallet_id"] == result["agent"]["wallet_id"]
    assert (
        result["denial"]["receipt"]["permit_id"]
        == result["permit"]["permit_id"]
    )
    assert result["denial"]["receipt_valid"] is True
    assert result["denial"]["debit_entry_ids_after"] == result["denial"][
        "debit_entry_ids_before"
    ]
    assert result["denial"]["denied_tool_debits"] == []


def test_agent_ops_war_room_cli_json_proves_control_plane_loop():
    result = subprocess.run(
        [sys.executable, "scripts/agent_ops_war_room_demo.py", "--assert", "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout)
    assert proof["status"] == "pass"
    assert proof["permit"]["permit_id"].startswith("permit-")
    assert proof["discovery"]["war_room_tools_discoverable"] is True
    assert proof["discovery"]["war_room_tool_names"] == [ALLOWED_TOOL, DENIED_TOOL]
    assert proof["invoke"]["receipt"]["outcome"] == "success"
    assert proof["replay"]["same_receipt"] is True
    assert proof["ledger"]["matching_debits"] == 1
    assert proof["audit"]["chain"]["valid"] is True
    assert proof["denial"]["reason"] == "permit_tool_not_allowed"
    assert proof["denial"]["receipt"]["outcome"] == "denied"
    assert proof["denial"]["receipt"]["tool"] == DENIED_TOOL
    assert proof["denial"]["receipt"]["ledger_entry_id"] is None
    assert proof["denial"]["receipt"]["credits_charged"] == "0"
    assert proof["denial"]["receipt_valid"] is True
    assert proof["denial"]["debit_entry_ids_after"] == proof["denial"][
        "debit_entry_ids_before"
    ]
    assert proof["denial"]["denied_tool_debits"] == []


@pytest.mark.anyio
async def test_run_in_process_restores_imported_process_state(
    clean_database,
    monkeypatch,
    tmp_path,
):
    previous_engine = database_module._engine
    previous_session_factory = database_module._session_factory
    previous_signing_key_service = get_signing_key_service()

    raw_private_key = Ed25519PrivateKey.generate().private_bytes(
        Encoding.Raw,
        PrivateFormat.Raw,
        NoEncryption(),
    )
    caller_env = {
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "VALID_API_KEYS": "test-key",
        "TRUST_MODE_ENABLED": "false",
        "ALLOW_LEGACY_UNPERMITTED_MCP": "true",
        "TRUST_SIGNING_KEY_ID": "caller-ed25519",
        "TRUST_SIGNING_PRIVATE_KEY_B64": base64.b64encode(raw_private_key).decode(),
    }
    for key, value in caller_env.items():
        monkeypatch.setenv(key, value)

    get_settings.cache_clear()
    caller_settings = get_settings()
    mcp_router.settings = caller_settings

    demo_db = tmp_path / "war-room-demo.db"
    result = await run_in_process(
        database_url=f"sqlite+aiosqlite:///{demo_db}",
        bootstrap_api_key="war-room-bootstrap-key",
        emit=False,
    )

    assert result["status"] == "pass"
    assert {key: os.environ.get(key) for key in caller_env} == caller_env
    assert get_settings().DATABASE_URL == caller_env["DATABASE_URL"]
    assert get_settings().VALID_API_KEYS == caller_env["VALID_API_KEYS"]
    assert get_settings().TRUST_MODE_ENABLED is False
    assert get_settings().ALLOW_LEGACY_UNPERMITTED_MCP is True
    assert get_settings().TRUST_SIGNING_KEY_ID == caller_env["TRUST_SIGNING_KEY_ID"]
    assert app_main.settings.TRUST_SIGNING_KEY_ID == caller_env["TRUST_SIGNING_KEY_ID"]
    assert auth_module.settings.VALID_API_KEYS == caller_env["VALID_API_KEYS"]
    assert discover_router.settings.DATABASE_URL == caller_env["DATABASE_URL"]
    assert mcp_router.settings.TRUST_MODE_ENABLED is False
    assert well_known_router.settings.DATABASE_URL == caller_env["DATABASE_URL"]
    assert database_module._engine is previous_engine
    assert database_module._session_factory is previous_session_factory
    assert get_signing_key_service() is previous_signing_key_service
