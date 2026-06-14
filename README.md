# GatewayKit

A lightweight, config-driven API gateway built from scratch in Python.

## Setup

```bash
pip install -r requirements.txt
```

## Running the Gateway

```bash
python main.py gateway.yaml
```

Or with an environment variable:

```bash
GATEWAY_CONFIG=gateway.yaml python main.py
```

The gateway starts on the port defined in your config (default 8080).

## Running the Tests

```bash
pytest tests/ -v
```

Tests spin up the gateway and mock upstream servers in-process — no external processes needed.

## Implemented Features

- [x] Config loading from YAML (CLI arg or `GATEWAY_CONFIG` env var)
- [x] `GET /health` — always returns `{"status": "healthy", "uptime_seconds": <int>}`
- [x] Basic proxying — forwards requests to upstream, returns response
- [x] 404 for unmatched routes
- [x] 405 for disallowed HTTP methods
- [x] `strip_prefix` — strips route path prefix before forwarding
- [x] Per-route timeout override + global timeout fallback
- [x] Rate limiting — fixed window strategy
- [x] Rate limiting — sliding window strategy
- [x] Rate limiting — per-IP and global bucket keys
- [x] Rate limiting — route-level config overrides global default
- [x] Retry with fixed and exponential backoff
- [x] Retry on configurable status codes
- [x] Request header transforms (add/remove)
- [x] Response header transforms (add/remove)
- [x] Response body envelope wrapping
- [x] Request body dot-notation mapping
- [x] API key authentication (configurable header)
- [x] Circuit breaker (threshold, window, cooldown, 503 response)
- [x] Load balancing — round robin
- [x] Load balancing — weighted round robin

## Not Implemented

- Upstream health checks (background polling against `/healthz` — would need a goroutine-style background loop; deprioritized given time constraints)

## Prerequisites

- Python 3.10+
- `pip install -r requirements.txt`
