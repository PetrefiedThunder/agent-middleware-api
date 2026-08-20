"""Contracts for the wallet-scoped smoke loop and the mint that feeds it.

The loop is meant to run unattended against a live deployment on a credential
that is *not* the admin key. These tests pin the properties that make that
safe — argument derivation, credential redaction, the off-loopback guard —
without needing a server, so they run in CI alongside everything else.
"""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOOP = ROOT / "scripts" / "scoped_smoke_loop.py"
BOOTSTRAP = ROOT / "scripts" / "partner_api_key_bootstrap.py"


def _load_loop(monkeypatch, *, api_key: str = "b2a_test_key", api_url: str = ""):
    """Import the loop with a chosen environment.

    Module-level constants read the environment at import time, so the env has
    to be set before ``run_path`` rather than after.
    """
    monkeypatch.setenv("AGENT_MIDDLEWARE_API_KEY", api_key)
    if api_url:
        monkeypatch.setenv("AGENT_MIDDLEWARE_API_URL", api_url)
    else:
        monkeypatch.delenv("AGENT_MIDDLEWARE_API_URL", raising=False)
    return runpy.run_path(str(LOOP))


def test_arguments_are_derived_from_each_tool_schema(monkeypatch) -> None:
    """A fixed payload shape only ever fits the registry it was written for."""

    arguments_for = _load_loop(monkeypatch)["arguments_for"]

    schema = {
        "type": "object",
        "required": ["session_id", "count", "ratio", "flag", "items", "meta"],
        "properties": {
            "session_id": {"type": "string"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
            "items": {"type": "array"},
            "meta": {"type": "object"},
            "ignored": {"type": "string"},
        },
    }
    built = arguments_for(schema, "run1")

    # Only required properties: sending optional ones invents intent the
    # caller never expressed.
    assert set(built) == {"session_id", "count", "ratio", "flag", "items", "meta"}
    assert built["session_id"] == "smoke-run1"
    assert built["count"] == 1
    assert built["ratio"] == 1.0
    assert built["flag"] is False
    assert built["items"] == []
    assert built["meta"] == {}


def test_argument_derivation_prefers_declared_defaults_and_enums(
    monkeypatch,
) -> None:
    """A schema that states an acceptable value is more trustworthy than a guess."""

    arguments_for = _load_loop(monkeypatch)["arguments_for"]

    built = arguments_for(
        {
            "required": ["mode", "region"],
            "properties": {
                "mode": {"type": "string", "enum": ["preview", "commit"]},
                "region": {"type": "string", "default": "us-east-1"},
            },
        },
        "run2",
    )
    assert built["mode"] == "preview"
    assert built["region"] == "us-east-1"


def test_argument_derivation_tolerates_a_schemaless_tool(monkeypatch) -> None:
    arguments_for = _load_loop(monkeypatch)["arguments_for"]

    assert arguments_for({}, "run3") == {}
    assert arguments_for(None, "run3") == {}


def test_response_bodies_never_echo_the_credential(monkeypatch) -> None:
    """A 4xx body can quote the key back; this loop logs into shared places."""

    module = _load_loop(monkeypatch, api_key="b2a_supersecret_value")
    redact = module["_redact"]

    body = '{"error":"invalid_api_key","supplied":"b2a_supersecret_value"}'
    scrubbed = redact(body, limit=500)
    assert "b2a_supersecret_value" not in scrubbed
    assert "<redacted>" in scrubbed


def test_spend_field_rename_fails_loudly(monkeypatch) -> None:
    """Reading spend back is how the no-double-charge check has any teeth.

    If the field were renamed and this silently returned 0, the replay check
    would compare 0 to 0 and pass while the invariant went unverified.
    """

    _spent = _load_loop(monkeypatch)["_spent"]

    assert _spent({"spent_credits": "15.0"}) == 15.0
    assert _spent({"credits_spent": 2}) == 2.0
    with pytest.raises(KeyError):
        _spent({"permit_id": "permit-1", "max_credits": "20"})


def test_off_loopback_runs_require_a_pinned_tool() -> None:
    """Nobody should discover their way into invoking production every 5 minutes."""

    result = subprocess.run(
        [sys.executable, str(LOOP), "--once"],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "AGENT_MIDDLEWARE_API_URL": "https://api.thisisatest.tech",
            "AGENT_MIDDLEWARE_API_KEY": "b2a_placeholder",
        },
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "refusing to auto-discover" in result.stderr
    # The guard must fire before any network call, and must not leak the key.
    assert "b2a_placeholder" not in result.stdout + result.stderr


def test_loopback_runs_may_discover(monkeypatch, tmp_path) -> None:
    """The pin is a production guard, not a burden on local development."""

    result = subprocess.run(
        [sys.executable, str(LOOP), "--once"],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "AGENT_MIDDLEWARE_API_URL": "http://127.0.0.1:1",
            "AGENT_MIDDLEWARE_API_KEY": "b2a_placeholder",
        },
    )
    # Port 1 refuses the connection, so this fails — but as a failed check
    # inside a running loop, not as the off-loopback refusal.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "refusing to auto-discover" not in result.stderr


def test_loop_requires_a_key_and_never_takes_one_as_an_argument() -> None:
    result = subprocess.run(
        [sys.executable, str(LOOP), "--once", "--tool", "x"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "AGENT_MIDDLEWARE_API_URL": "http://127.0.0.1:1"},
    )
    assert result.returncode != 0
    assert "AGENT_MIDDLEWARE_API_KEY is not set" in result.stderr

    help_text = subprocess.run(
        [sys.executable, str(LOOP), "--help"], capture_output=True, text=True
    ).stdout
    assert "--api-key" not in help_text, (
        "a key passed as an argument is visible in process listings"
    )


def test_bootstrap_key_only_and_json_are_mutually_exclusive() -> None:
    """Two output modes writing to stdout at once would corrupt either pipe."""

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--api-url",
            "https://api.example.org",
            "--key-only",
            "--json",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "BOOTSTRAP_KEY": "placeholder"},
    )
    assert result.returncode != 0
    assert "mutually exclusive" in result.stderr


def test_bootstrap_still_refuses_to_mint_without_a_bootstrap_secret() -> None:
    """--key-only must not have opened a path that skips the fail-closed check."""

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--api-url",
            "https://api.example.org",
            "--key-only",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "BOOTSTRAP_KEY" in result.stderr
