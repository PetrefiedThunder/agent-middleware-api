"""
Conversion utilities between SQLModel database rows and Pydantic API schemas.
"""

import json
from typing import Any

from datetime import datetime, timezone

from ..schemas.billing import (
    WalletResponse,
    WalletType,
    WalletStatus,
    LedgerEntry,
    LedgerAction,
    ServiceCategory,
    BillingAlert,
    AlertType,
    AlertSeverity,
    KYCStatus,
)
from ..schemas.oracle import (
    CompatibilityTier,
    DirectoryType,
    IndexedAPI,
    IndexedCapability,
    OracleStatus,
    RegistrationResult,
)
from ..schemas.telemetry import (
    TelemetryEvent,
    TelemetryEventType,
    Severity,
)
from .models import (
    WalletModel,
    LedgerEntryModel,
    BillingAlertModel,
    OracleCrawlTargetModel,
    OracleIndexedAPIModel,
    OracleRegistrationModel,
    TelemetryEventModel,
)


def wallet_model_to_response(
    wallet: WalletModel,
) -> WalletResponse:
    """Convert a WalletModel to a WalletResponse Pydantic schema."""
    metadata = {}
    if wallet.metadata_json:
        try:
            metadata = json.loads(wallet.metadata_json)
        except json.JSONDecodeError:
            pass

    kyc_status_str = wallet.kyc_status or "not_required"
    try:
        kyc_status = KYCStatus(kyc_status_str)
    except ValueError:
        kyc_status = KYCStatus.NOT_REQUIRED

    return WalletResponse(
        wallet_id=wallet.wallet_id,
        wallet_type=WalletType(wallet.wallet_type),
        owner_name=wallet.owner_name,
        email=wallet.email,
        balance=wallet.balance,
        lifetime_credits=wallet.lifetime_credits,
        lifetime_debits=wallet.lifetime_debits,
        sponsor_wallet_id=wallet.parent_wallet_id,
        agent_id=wallet.agent_id,
        child_agent_id=wallet.child_agent_id,
        max_spend=wallet.max_spend,
        task_description=wallet.task_description,
        ttl_seconds=wallet.ttl_seconds,
        daily_limit=wallet.daily_limit,
        auto_refill=wallet.auto_refill,
        auto_refill_threshold=wallet.auto_refill_threshold,
        auto_refill_amount=wallet.auto_refill_amount,
        status=WalletStatus(wallet.status),
        kyc_status=kyc_status,
        created_at=wallet.created_at,
        metadata=metadata,
    )


def ledger_entry_model_to_schema(
    entry: LedgerEntryModel,
) -> LedgerEntry:
    """Convert a LedgerEntryModel to a LedgerEntry Pydantic schema."""
    metadata = {}
    if entry.metadata_json:
        try:
            metadata = json.loads(entry.metadata_json)
        except json.JSONDecodeError:
            pass

    return LedgerEntry(
        entry_id=entry.entry_id,
        wallet_id=entry.wallet_id,
        action=LedgerAction(entry.action),
        amount=entry.amount,
        balance_after=entry.balance_after,
        service_category=(
            ServiceCategory(entry.service_category)
            if entry.service_category
            else None
        ),
        description=entry.description,
        request_path=entry.request_path,
        compute_cost=entry.compute_cost,
        margin=entry.margin,
        timestamp=entry.timestamp,
        metadata=metadata,
    )


def billing_alert_model_to_schema(
    alert: BillingAlertModel,
) -> BillingAlert:
    """Convert a BillingAlertModel to a BillingAlert Pydantic schema."""
    return BillingAlert(
        alert_id=alert.alert_id,
        wallet_id=alert.wallet_id,
        alert_type=AlertType(alert.alert_type),
        threshold_amount=alert.threshold_amount,
        current_balance=alert.current_balance,
        message=alert.message,
        severity=AlertSeverity(alert.severity),
        acknowledged=alert.acknowledged,
        created_at=alert.created_at,
    )


def metadata_dict_to_json(metadata: dict[str, Any] | None) -> str | None:
    """Convert a metadata dict to JSON string for database storage."""
    if not metadata:
        return None
    return json.dumps(metadata, default=str)


def parse_metadata_json(metadata_json: str | None) -> dict[str, Any]:
    """Parse metadata JSON string to dict."""
    if not metadata_json:
        return {}
    try:
        return json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def telemetry_event_to_model(
    event_id: str,
    batch_id: str,
    event: TelemetryEvent,
    ingested_at: datetime,
) -> TelemetryEventModel:
    """Convert a TelemetryEvent API schema + storage metadata into a row."""
    return TelemetryEventModel(
        event_id=event_id,
        batch_id=batch_id,
        event_type=event.event_type.value,
        severity=event.severity.value,
        source=event.source,
        message=event.message,
        stack_trace=event.stack_trace,
        payload_json=metadata_dict_to_json(event.metadata),
        event_timestamp=event.timestamp,
        ingested_at=ingested_at,
    )


def telemetry_event_model_to_schema(row: TelemetryEventModel) -> TelemetryEvent:
    """Rebuild a TelemetryEvent from its stored row."""
    return TelemetryEvent(
        event_type=TelemetryEventType(row.event_type),
        source=row.source,
        message=row.message,
        severity=Severity(row.severity),
        stack_trace=row.stack_trace,
        metadata=parse_metadata_json(row.payload_json),
        timestamp=row.event_timestamp,
    )


# ---------------------------------------------------------------------------
# Oracle
# ---------------------------------------------------------------------------

def indexed_api_to_model(api: IndexedAPI) -> OracleIndexedAPIModel:
    """Flatten an IndexedAPI schema into its stored row."""
    return OracleIndexedAPIModel(
        api_id=api.api_id,
        url=api.url,
        name=api.name,
        description=api.description,
        directory_type=api.directory_type.value,
        compatibility_tier=api.compatibility_tier.value,
        compatibility_score=api.compatibility_score,
        capabilities_json=json.dumps(
            [c.model_dump() for c in api.capabilities], default=str
        ),
        tags_json=json.dumps(api.tags, default=str),
        status=api.status.value,
        last_crawled=api.last_crawled,
    )


def indexed_api_model_to_schema(row: OracleIndexedAPIModel) -> IndexedAPI:
    """Rebuild an IndexedAPI from its row."""
    caps: list[IndexedCapability] = []
    if row.capabilities_json:
        try:
            for item in json.loads(row.capabilities_json):
                caps.append(IndexedCapability.model_validate(item))
        except (json.JSONDecodeError, ValueError):
            pass

    tags: list[str] = []
    if row.tags_json:
        try:
            parsed = json.loads(row.tags_json)
            if isinstance(parsed, list):
                tags = [str(t) for t in parsed]
        except json.JSONDecodeError:
            pass

    return IndexedAPI(
        api_id=row.api_id,
        url=row.url,
        name=row.name,
        description=row.description,
        directory_type=DirectoryType(row.directory_type),
        capabilities=caps,
        compatibility_tier=CompatibilityTier(row.compatibility_tier),
        compatibility_score=row.compatibility_score,
        tags=tags,
        last_crawled=row.last_crawled,
        status=OracleStatus(row.status),
    )


def registration_result_to_model(
    result: RegistrationResult,
) -> OracleRegistrationModel:
    """Store a RegistrationResult. Requires a non-null registration_id —
    caller (oracle.RegistrationEngine.register) always produces one on
    success; failures synthesize one before storing."""
    return OracleRegistrationModel(
        registration_id=result.registration_id or "",
        directory_url=result.directory_url,
        directory_type=result.directory_type.value,
        status=result.status.value,
        message=result.message,
    )


def registration_model_to_schema(
    row: OracleRegistrationModel,
) -> RegistrationResult:
    return RegistrationResult(
        directory_url=row.directory_url,
        directory_type=DirectoryType(row.directory_type),
        status=OracleStatus(row.status),
        registration_id=row.registration_id or None,
        message=row.message,
    )
