# GatewayKit

**Henish Patel** — Podium SWE Take-Home

A config-driven HTTP API gateway built from scratch in Python. Reads a `gateway.yaml` file and handles routing, rate limiting, retries, transforms, auth, and circuit breaking — no proxy frameworks used.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running the Gateway

Pass the config file as a CLI argument:

```bash
python main.py gateway.yaml
```

Or use the environment variable:

```bash
GATEWAY_CONFIG=gateway.yaml python main.py
```

The gateway starts on the port defined in the config (default 8080). Hit `GET /health` to confirm it's up:

```bash
curl http://localhost:8080/health
# {"status": "healthy", "uptime_seconds": 4}
```

---

## Running the Tests

```bash
pytest tests/ -v
```

Tests spin up the gateway and all mock upstream servers in-process — no external services needed. All 21 tests should pass.

---

## Implemented Features

- [x] Config loading from YAML via CLI arg or `GATEWAY_CONFIG` env var
- [x] `GET /health` — always returns `{"status": "healthy", "uptime_seconds": <int>}`
- [x] Route matching with prefix anchoring (no false matches on `/api/users-old`)
- [x] 404 for unmatched routes, 405 for disallowed methods
- [x] `strip_prefix` — strips the route prefix before forwarding to upstream
- [x] Global timeout with per-route override
- [x] Rate limiting — fixed window strategy
- [x] Rate limiting — sliding window strategy
- [x] Rate limiting — per-IP and global bucket keys
- [x] Route-level rate limit overrides the global default
- [x] Retry with fixed and exponential backoff on configurable status codes
- [x] Request header transforms (add and remove)
- [x] Request body mapping — dot-notation destination paths, `$literal:` values, `$request_time`
- [x] Response header transforms (add and remove)
- [x] Response body envelope wrapping with `$body`, `$response_time`, `$route_path`
- [x] API key authentication via configurable header
- [x] Circuit breaker — trips after N failures in a window, returns 503 with `retry_after`
- [x] Load balancing — round robin and weighted round robin across multiple upstream targets

