# LangChain + Agent Middleware API

LangChain integration for the Agent Middleware API via governed **permit → invoke → receipt** flow.

All tool invocations go through the trust plane: scoped permits, signed receipts, replay protection, and metered billing.

## Installation

This package is not published to PyPI. Install it from a checkout of
this repository:

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
python -m pip install -e ./b2a_sdk
python -m pip install -e wrappers/langchain-agent-middleware
```

`b2a_sdk` must be installed from the local path first: this package
depends on `b2a-sdk>=0.3.0`, which is not on PyPI, so installing the
wrapper on its own fails to resolve. That installs the `langchain_b2a`
module used below.

## Quick Start (Governed Flow)

```python
from langchain_b2a import B2AClient, get_langgraph_tools
from langgraph.prebuilt import create_react_agent

# Initialize client
client = B2AClient(api_key="your-api-key")

# Get LangGraph-compatible tools with wallet_id
tools = get_langgraph_tools(client, wallet_id="agent-001")

# Create agent
model = ChatOpenAI(model="gpt-4o")
agent = create_react_agent(model, tools)
```

## MCP Tools via Governed Flow

```python
from langchain_b2a import B2AClient, get_mcp_tools

client = B2AClient(api_key="...")
mcp_tools = get_mcp_tools(client, wallet_id="agent-001")
tool = mcp_tools[0]

# Call an MCP tool with caller-supplied idempotency key
# The wrapper creates a permit, invokes the tool, and returns a signed receipt
result = await tool.ainvoke({
    "tool_name": "data-indexer",
    "idempotency_key": "unique-key-123",  # REQUIRED: caller must supply
    "arguments": {"documents": ["..."]},
})

# Result includes signed receipt
# {'content': [...], 'receipt_id': '...', 'credits_charged': '2', 'signature': '...'}
```

## Idempotency and Replay Protection

The `idempotency_key` is **required** and must be supplied by the caller. Do not auto-generate keys.

Replaying the same `idempotency_key` returns the original receipt without recharging:

```python
# First call: charges credits
result1 = await tool.ainvoke({
    "tool_name": "partner.search",
    "idempotency_key": "search-abc-123",
    "arguments": {"query": "test"},
})

# Replay: returns cached receipt, no additional charge
result2 = await tool.ainvoke({
    "tool_name": "partner.search",
    "idempotency_key": "search-abc-123",  # same key
    "arguments": {"query": "different"},  # different args ignored
})
```

## Permit Configuration

Control permit budget and TTL:

```python
from decimal import Decimal

tools = get_mcp_tools(
    client,
    wallet_id="agent-001",
    permit_budget=Decimal("50"),  # max 50 credits per permit
    permit_ttl_minutes=15,         # permit expires in 15 minutes
)
```

## Requirements

- Python 3.11+
- LangChain 0.1.0+
- httpx 0.25.0+
