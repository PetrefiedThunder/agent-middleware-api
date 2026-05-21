"""The trust plane — the frozen product spine of Agent Middleware API.

This package is a stable, import-light boundary over the trust-plane primitives
that constitute the core product:

    permits -> governed invocation -> idempotency -> wallet ledger (metering)
    -> receipts -> audit verification -> evidence

Everything outside this boundary is a protocol adapter or an example workload.
The modules here re-export the canonical implementations that live under
``app.services`` / ``app.policy`` so callers can depend on the product core
through one obvious namespace without coupling to internal module layout.

No behavior lives here that is not also reachable through the underlying
service modules; this is a facade, not a fork.
"""

from __future__ import annotations

from .adapters import (
    GovernedInvocationAdapter,
    GovernedRequest,
    GovernedResult,
    McpGovernedAdapter,
)
from .audit_chain import (
    AuditChainVerification,
    audit_payload,
    record_audit_event,
    sign_audit_model,
    verify_audit_chain,
)
from .evidence import build_evidence_bundle, build_receipt_evidence
from .idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyReplay,
    IdempotencyService,
    get_idempotency_service,
)
from .metering import (
    AgentMoney,
    InsufficientFundsError,
    WalletNotFoundError,
    get_agent_money,
)
from .permits import (
    PermitError,
    PermitService,
    PermitValidation,
    get_permit_service,
)
from .policy import (
    PolicyDecision,
    PolicyEvaluation,
    evaluate_governed_action,
    evaluate_tool_invocation,
    evaluate_wallet_policy,
    record_governed_action,
)
from .receipts import ReceiptError, ReceiptService, get_receipt_service

__all__ = [
    # adapters
    "GovernedInvocationAdapter",
    "GovernedRequest",
    "GovernedResult",
    "McpGovernedAdapter",
    # permits
    "PermitService",
    "PermitValidation",
    "PermitError",
    "get_permit_service",
    # receipts
    "ReceiptService",
    "ReceiptError",
    "get_receipt_service",
    # idempotency
    "IdempotencyService",
    "IdempotencyReplay",
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "get_idempotency_service",
    # audit
    "verify_audit_chain",
    "sign_audit_model",
    "audit_payload",
    "AuditChainVerification",
    "record_audit_event",
    # policy
    "evaluate_tool_invocation",
    "evaluate_governed_action",
    "evaluate_wallet_policy",
    "record_governed_action",
    "PolicyDecision",
    "PolicyEvaluation",
    # metering
    "AgentMoney",
    "get_agent_money",
    "InsufficientFundsError",
    "WalletNotFoundError",
    # evidence
    "build_receipt_evidence",
    "build_evidence_bundle",
]
