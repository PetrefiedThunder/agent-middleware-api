# Trust Model

The trust model is intentionally narrow: governed MCP tool calls are the first
hard trust boundary.

## Signed Permits

`POST /v1/permits` creates Ed25519-signed authority for a wallet-scoped agent.
A permit binds:

- issuer wallet
- subject wallet
- optional subject API key
- allowed tools
- scopes such as `tool:{tool_name}:invoke` and `billing:charge`
- maximum credits
- expiry
- nonce
- revocation state

Permit creation requires `Idempotency-Key`. Reusing the same key with the same
request returns the original permit. Reusing it with a different request fails
with `409 Conflict`.

## Governed MCP Calls

A governed MCP call supplies `permit_id` and `idempotency_key` in `mcpContext`
or the `Idempotency-Key` header. The server validates wallet binding, key
binding, tool scope, budget, expiry, revocation, and signature before charging.

Legacy wallet-only MCP calls remain available while `TRUST_MODE_ENABLED=false`.
Production trust mode should run with `ALLOW_LEGACY_UNPERMITTED_MCP=false`.

## Exactly-Once Debit, Bound To The Idempotency Record

This is the primitive the rest of the model exists to protect, and the one that
distinguishes this system — signed receipts do not (see
[`WEDGE.md`](WEDGE.md) §"Signed receipts are table stakes now").

One accepted idempotency key produces **exactly one gateway dispatch, one ledger
debit, and one receipt**, linked by a single persisted chain. The ledger entry
carries the idempotency record's identity as its `operation_key` under a
uniqueness constraint, so a duplicate debit cannot be written even if two
processes race. Replaying the same request under the same accepted key returns
the original result and receipt without a second dispatch or debit; replaying a
*changed* request under that key fails closed with `409 Conflict`.

Budgets are enforced before money moves: a permit's cap is checked in the same
atomic conditional update that consumes it, so concurrent invocations cannot
overspend it.

**Ambiguity is a first-class durable state.** For the configured upstream MCP
tool, a dispatch attempt is persisted through
`prepared → dispatched → {succeeded, returned_error, delivery_uncertain,
response_rejected}`. If the process dies after the request left the gateway but
before an acknowledgement arrived, recovery classifies the attempt as
`delivery_uncertain`: **the charge stands and the call is never redispatched**,
because non-delivery can no longer be proven. Local (non-upstream) governed tools
have no dispatch state machine; a crash there fails closed into manual review
instead. See [`docs/failure-semantics.md`](docs/failure-semantics.md).

This is at-most-one *gateway* dispatch plus refusal to redispatch an ambiguous
invocation. It is **not** effect-once inside an arbitrary upstream tool, which
requires that tool to honour the forwarded idempotency key.

## Signed Receipts

Every successful governed MCP call produces a signed receipt linked to the
permit, ledger entry, audit event, tool, request hash, response hash, and cost.
Denied and failed governed attempts produce signed denial/failure receipts when
a valid permit was present.

The receipt's Ed25519 signature covers the **ledger entry, the idempotency
record, and the dispatch attempt together**, so the link between the authority,
the money, and the delivery outcome is verifiable offline rather than asserted.
Signed receipts are widely available elsewhere; that binding is what this
signature adds.

## Audit Chain

Control-plane audit events include a payload hash, previous hash, chain hash,
signature, and signing key ID. `/v1/audit/verify-chain` verifies wallet-scoped
audit integrity and detects silent mutation.

## Key Material

The database stores public keys and key metadata only. Production private keys
must come from configured secret material or KMS-backed injection. Local tests
may use process-ephemeral keys; they are not persisted.
