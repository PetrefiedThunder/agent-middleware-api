"""
Agent-Native Communications Layer
===================================
Handles agent-to-agent messaging without human-first platforms.

Why not Gmail/Slack?
- Human spam filters block automated senders
- Rate limits designed for humans (~500/day) throttle agent workloads
- OAuth flows require browser interaction (violates Zero-GUI rule)

This module implements the Agent Mail pattern: structured, authenticated,
machine-to-machine messaging with built-in routing and delivery confirmation.
"""

import asyncio
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message Types
# ---------------------------------------------------------------------------

class MessagePriority(str, Enum):
    CRITICAL = "critical"   # Immediate delivery, retry aggressively
    HIGH = "high"           # Deliver within 1 minute
    NORMAL = "normal"       # Deliver within 5 minutes
    LOW = "low"             # Batch delivery, best effort


class MessageType(str, Enum):
    """Standard message types for agent-to-agent communication."""
    REQUEST = "request"         # Asking another agent to do something
    RESPONSE = "response"       # Reply to a request
    EVENT = "event"             # Notification of something that happened
    HEARTBEAT = "heartbeat"     # Liveness check
    HANDOFF = "handoff"         # Transfer responsibility to another agent


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@dataclass
class AgentMessage:
    """A single agent-to-agent message."""
    message_id: str
    from_agent: str          # Sender agent identifier
    to_agent: str            # Recipient agent identifier
    message_type: MessageType
    priority: MessagePriority
    subject: str
    body: dict               # Structured payload (always JSON-serializable)
    correlation_id: str | None = None  # Links request/response pairs
    reply_to: str | None = None        # Message ID this replies to
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    delivery_status: DeliveryStatus = DeliveryStatus.QUEUED
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------

@dataclass
class RegisteredAgent:
    """An agent registered in the communications network."""
    agent_id: str
    name: str
    capabilities: list[str]   # What this agent can do
    webhook_url: str | None    # Where to deliver messages
    api_key: str               # Auth for sending/receiving
    owner_key: str = ""        # RED TEAM FIX: API key of the registering tenant
    status: str = "active"
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime | None = None
    message_count: int = 0


class AgentRegistry:
    """Registry of agents in the communication network."""

    def __init__(self):
        self._agents: dict[str, RegisteredAgent] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        name: str,
        capabilities: list[str],
        webhook_url: str | None = None,
        owner_key: str = "",
    ) -> RegisteredAgent:
        agent = RegisteredAgent(
            agent_id=f"agent-{uuid.uuid4().hex[:12]}",
            name=name,
            capabilities=capabilities,
            webhook_url=webhook_url,
            api_key=f"ak-{uuid.uuid4().hex}",
            owner_key=owner_key,
        )
        async with self._lock:
            self._agents[agent.agent_id] = agent
        logger.info(f"Agent registered: {agent.agent_id} ({agent.name})")
        return agent

    async def get(self, agent_id: str) -> RegisteredAgent | None:
        return self._agents.get(agent_id)

    async def find_by_capability(self, capability: str) -> list[RegisteredAgent]:
        """Find agents that advertise a specific capability."""
        return [
            a for a in self._agents.values()
            if capability in a.capabilities and a.status == "active"
        ]

    async def list_all(self) -> list[RegisteredAgent]:
        return list(self._agents.values())


# ---------------------------------------------------------------------------
# Message Router
# ---------------------------------------------------------------------------

class MessageRouter:
    """
    Routes messages between agents with delivery guarantees.

    Delivery strategies by priority:
    - CRITICAL: Immediate webhook delivery with 3x retry
    - HIGH: Deliver within 1 minute, 2x retry
    - NORMAL: Deliver within 5 minutes, 1x retry
    - LOW: Batch delivery every 5 minutes, no retry
    """

    def __init__(self, registry: AgentRegistry):
        self._registry = registry
        self._inbox: dict[str, list[AgentMessage]] = {}  # agent_id → messages
        self._outbox: list[AgentMessage] = []
        self._lock = asyncio.Lock()

    async def send(self, message: AgentMessage) -> AgentMessage:
        """Route a message to the recipient."""
        recipient = await self._registry.get(message.to_agent)
        if not recipient:
            message.delivery_status = DeliveryStatus.FAILED
            logger.warning(f"Message {message.message_id} failed: recipient {message.to_agent} not found")
            return message

        # Add to recipient's inbox
        async with self._lock:
            if message.to_agent not in self._inbox:
                self._inbox[message.to_agent] = []
            self._inbox[message.to_agent].append(message)
            self._outbox.append(message)

        # Attempt delivery
        if recipient.webhook_url:
            delivered = await self._deliver_webhook(message, recipient)
            if delivered:
                message.delivery_status = DeliveryStatus.DELIVERED
                message.delivered_at = datetime.now(timezone.utc)
            else:
                message.delivery_status = DeliveryStatus.QUEUED
        else:
            # No webhook — agent must poll
            message.delivery_status = DeliveryStatus.QUEUED

        logger.info(
            f"Message routed: {message.from_agent} → {message.to_agent} "
            f"[{message.message_type.value}] status={message.delivery_status.value}"
        )
        return message

    async def poll(self, agent_id: str, limit: int = 50) -> list[AgentMessage]:
        """Poll for messages in an agent's inbox."""
        async with self._lock:
            messages = self._inbox.get(agent_id, [])[:limit]
            # Mark as delivered
            for msg in messages:
                if msg.delivery_status == DeliveryStatus.QUEUED:
                    msg.delivery_status = DeliveryStatus.DELIVERED
                    msg.delivered_at = datetime.now(timezone.utc)
        return messages

    async def acknowledge(self, agent_id: str, message_id: str) -> bool:
        """Acknowledge receipt of a message."""
        async with self._lock:
            messages = self._inbox.get(agent_id, [])
            for msg in messages:
                if msg.message_id == message_id:
                    msg.delivery_status = DeliveryStatus.ACKNOWLEDGED
                    msg.acknowledged_at = datetime.now(timezone.utc)
                    return True
        return False

    async def _deliver_webhook(self, message: AgentMessage, recipient: RegisteredAgent) -> bool:
        """Deliver message via webhook. Production: use httpx with retry."""
        # Stub: simulate webhook delivery
        logger.info(f"Webhook delivery to {recipient.webhook_url} for {message.message_id}")
        return True


# ---------------------------------------------------------------------------
# Agent Comms Orchestrator
# ---------------------------------------------------------------------------

class AgentComms:
    """
    Top-level orchestrator for agent-to-agent communications.
    Provides a clean interface for the router layer.
    """

    def __init__(self):
        self.registry = AgentRegistry()
        self.router = MessageRouter(self.registry)

    async def register_agent(
        self,
        name: str,
        capabilities: list[str],
        webhook_url: str | None = None,
        owner_key: str = "",
    ) -> RegisteredAgent:
        return await self.registry.register(name, capabilities, webhook_url, owner_key)

    async def send_message(
        self,
        from_agent: str,
        to_agent: str,
        message_type: MessageType,
        subject: str,
        body: dict,
        priority: MessagePriority = MessagePriority.NORMAL,
        correlation_id: str | None = None,
        reply_to: str | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            message_id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            priority=priority,
            subject=subject,
            body=body,
            correlation_id=correlation_id or str(uuid.uuid4()),
            reply_to=reply_to,
        )
        return await self.router.send(message)

    async def request_handoff(
        self,
        from_agent: str,
        capability: str,
        context: dict,
    ) -> AgentMessage | None:
        """
        Find an agent with the required capability and hand off work.
        This is how swarm intelligence works: agents route tasks to specialists.
        """
        candidates = await self.registry.find_by_capability(capability)
        if not candidates:
            logger.warning(f"No agents found with capability '{capability}'")
            return None

        # Pick the first available (production: load balance)
        target = candidates[0]
        return await self.send_message(
            from_agent=from_agent,
            to_agent=target.agent_id,
            message_type=MessageType.HANDOFF,
            subject=f"Handoff: {capability}",
            body={"capability": capability, "context": context},
            priority=MessagePriority.HIGH,
        )
