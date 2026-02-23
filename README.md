# Agent-Native Middleware API

[![CI](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
[![Auto PR](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/auto-pr.yml/badge.svg?branch=master)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/auto-pr.yml)

Headless FastAPI middleware for the Business-to-Agent (B2A) economy.  
Designed for autonomous clients that need infrastructure for messaging, billing, telemetry, content automation, and secure API operations.

## Core Pillars

- IoT Protocol Bridge (`/v1/iot`)
- Autonomous Product Manager + Telemetry (`/v1/telemetry`)
- Programmatic Media Engine (`/v1/media`)
- Agent Communications (`/v1/comms`)
- Content Factory (`/v1/factory`)
- Agent Oracle + Broadcast (`/v1/oracle`, `/v1/broadcast`)
- Agent Billing (`/v1/billing`)
- Red Team Security + RTaaS (`/v1/security`, `/v1/rtaas`)
- Launch Sequence + Sandbox + Protocol Generation

## Quick Start (Local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open:

- `http://localhost:8000/docs`
- `http://localhost:8000/health`
- `http://localhost:8000/health/dependencies`

## Deployment (Railway)

This repository is deployment-ready for Railway via `Dockerfile` + `railway.json`.

### 1. Create Service

1. Create a Railway project from this repository.
2. Use this repository root as the service root (contains `Dockerfile`).

CLI alternative:

```bash
railway login
railway init
railway up
```

### 2. Configure Environment Variables

Recommended baseline:

- `DEBUG=false`
- `VALID_API_KEYS=<comma-separated-keys>`
- `RATE_LIMIT_PER_MINUTE=120`
- `STATE_BACKEND=auto`
- `STATE_NAMESPACE=agent_middleware`
- `DATABASE_URL=<Railway Postgres connection string>`
- `REDIS_URL=<Railway Redis connection string>`

Optional:

- `MQTT_BROKER_URL=<external mqtt broker url>`
- `AUTO_PR_ENABLED=true|false`
- `GIT_REMOTE_URL=<target repo>`
- `GIT_BRANCH_PREFIX=auto-pm/`

Railway injects `PORT` automatically. The container binds to `PORT` at runtime.

### 3. Verify Deployment

- `GET /health` returns `200`
- `GET /health/dependencies` reports healthy state backend
- `GET /docs` loads OpenAPI UI
- protected endpoints accept `X-API-Key`

## Durability Model

- PostgreSQL: preferred durable state backend for runtime stores.
- Redis: distributed rate limiting and backend fallback state store.
- Memory: automatic fallback when no persistent backend is configured.

Current durable service stores:

- Billing (`wallets`, `ledger`, `alerts`)
- Comms (`agent registry`, `inbox`, `outbox`)
- Telemetry (`events`, `anomalies`)

## API Discovery Endpoints

- `GET /`
- `GET /openapi.json`
- `GET /llm.txt`
- `GET /.well-known/agent.json`
- `GET /docs/index`

## Configuration

Use `.env.example` as local template and `.env.production` as production reference.

Key groups:

- App/runtime: `APP_NAME`, `APP_VERSION`, `DEBUG`, `PORT`
- Auth: `API_KEY_HEADER`, `VALID_API_KEYS`
- Durability: `STATE_BACKEND`, `STATE_NAMESPACE`, `DATABASE_URL`, `REDIS_URL`
- IoT: `MQTT_BROKER_URL`, `MQTT_DEFAULT_QOS`, `MQTT_ENFORCE_TOPIC_ACL`
- Telemetry: `TELEMETRY_RETENTION_HOURS`, `AUTO_PR_ENABLED`

## Development

Run tests:

```bash
pytest -q
```

CI runs on Python `3.11` and `3.12` via GitHub Actions.

## Security

- API key authentication on protected endpoints.
- Per-key rate limiting middleware.
- Red Team scanning endpoints for pre-production hardening.

Report vulnerabilities using `/SECURITY.md`.

## Contributing

Please read `/CONTRIBUTING.md` before opening pull requests.

## License

MIT License. See `/LICENSE`.
