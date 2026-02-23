# Agent Middleware API

FastAPI service for agent-native middleware (IoT bridge, telemetry, media, comms, billing, launch orchestration).

## Railway Deployment

This repo is configured for Railway via `Dockerfile` + `railway.json`.

### 1. Create Service

1. Create a new Railway project/service from this repo.
2. Deploy from the repo root (the folder containing `Dockerfile`).

CLI option:

```bash
railway login
railway init
railway up
```

### 2. Configure Environment Variables

Set these in Railway service variables:

- `DEBUG=false`
- `VALID_API_KEYS=<comma-separated-keys>` (recommended for production)
- `RATE_LIMIT_PER_MINUTE=120` (optional override)
- `STATE_BACKEND=auto`
- `DATABASE_URL=<from Railway Postgres service>`
- `REDIS_URL=<from Railway Redis service>`
- `STATE_NAMESPACE=agent_middleware`

Optional integrations:

- `MQTT_BROKER_URL` for IoT messaging
- `AUTO_PR_ENABLED`, `GIT_REMOTE_URL`, `GIT_BRANCH_PREFIX` for autonomous PR flows

Railway will inject `PORT` automatically. The container now binds to `PORT` at runtime.

### 3. Verify Deployment

After deploy, check:

- `GET /health` returns `200`
- `GET /health/dependencies` reports `state_store.ok: true`
- `GET /docs` loads Swagger UI
- authenticated endpoints accept your `X-API-Key`

## Persistence Profile (Railway)

This service now supports durable runtime state:

- `PostgreSQL` (preferred): wallet/comms/telemetry state snapshots survive restarts
- `Redis`: distributed rate limiting and fallback durable snapshots when Postgres is not set
- `MQTT`: set `MQTT_BROKER_URL` to an external broker for IoT bridge traffic

Recommended Railway layout:

1. API service (this repo)
2. Postgres service
3. Redis service
4. Optional external MQTT provider (set URL in API env vars)

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
