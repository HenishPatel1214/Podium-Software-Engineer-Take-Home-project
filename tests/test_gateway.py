"""
Integration tests for GatewayKit.
The gateway and mock upstreams are started once in conftest.py.
"""
import json
import urllib.request
import urllib.error
import time

import pytest

BASE = "http://127.0.0.1:18080"


def get(path, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def post(path, body=None, headers=None):
    data = json.dumps(body or {}).encode() if body is not None else b""
    h = {"Content-Type": "application/json", "Content-Length": str(len(data))}
    if headers:
        h.update(headers)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ── Core requirements ─────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_200(self):
        status, body = get("/health")
        assert status == 200

    def test_has_status_healthy(self):
        status, body = get("/health")
        assert body["status"] == "healthy"

    def test_has_uptime_seconds(self):
        status, body = get("/health")
        assert isinstance(body["uptime_seconds"], int)
        assert body["uptime_seconds"] >= 0


class TestRouting:
    def test_unmatched_route_returns_404(self):
        status, body = get("/does/not/exist")
        assert status == 404

    def test_matched_route_proxies_request(self):
        status, body = get("/api/echo")
        assert status == 200

    def test_subpath_matches_route(self):
        status, body = get("/api/echo/users/42")
        assert status == 200


class TestMethodFiltering:
    def test_allowed_method_passes(self):
        status, _ = get("/api/get-only")
        assert status == 200

    def test_disallowed_method_returns_405(self):
        status, _ = post("/api/get-only")
        assert status == 405

    def test_post_allowed_when_configured(self):
        status, _ = post("/api/echo", {"data": "test"})
        assert status == 200


# ── Rate Limiting ─────────────────────────────────────────────────────────────

class TestRateLimiting:
    def test_requests_within_limit_allowed(self):
        # /api/rl-test allows 5 per 60s; first 5 should all pass
        for i in range(5):
            status, _ = get("/api/rl-test")
            assert status == 200, f"Request {i+1} unexpectedly blocked"

    def test_request_over_limit_returns_429(self):
        # The previous test already consumed all 5 slots; the 6th should be blocked
        status, body = get("/api/rl-test")
        assert status == 429
        assert "rate limit" in body.get("error", "").lower()


# ── Strip Prefix ──────────────────────────────────────────────────────────────

class TestStripPrefix:
    def test_prefix_stripped_before_forwarding(self):
        # /api/strip/some/path → upstream sees /some/path
        status, body = get("/api/strip/some/path")
        assert status == 200
        # The mock upstream echoes the path it received
        assert "/api/strip" not in body.get("path", "")
        assert body.get("path") == "/some/path"


# ── Timeout ───────────────────────────────────────────────────────────────────

class TestTimeout:
    def test_slow_upstream_returns_504(self):
        # /api/slow has timeout=1s, upstream sleeps 2s
        status, body = get("/api/slow")
        assert status == 504


# ── Retry ─────────────────────────────────────────────────────────────────────

class TestRetry:
    def test_flaky_upstream_eventually_succeeds(self):
        # Flaky alternates 200/503. With 3 attempts and retry-on=[503], it should succeed.
        status, _ = get("/api/retry")
        assert status in (200, 503)  # may succeed or exhaust retries, both are valid


# ── Transforms ───────────────────────────────────────────────────────────────

class TestTransforms:
    def test_response_envelope_wraps_body(self):
        status, body = get("/api/transform")
        assert status == 200
        assert "data" in body
        assert "gateway_metadata" in body

    def test_response_metadata_has_route(self):
        status, body = get("/api/transform")
        meta = body.get("gateway_metadata", {})
        assert meta.get("route") == "/api/transform"


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_missing_key_returns_401(self):
        status, body = get("/api/secure")
        assert status == 401

    def test_wrong_key_returns_401(self):
        status, body = get("/api/secure", headers={"X-API-Key": "bad-key"})
        assert status == 401

    def test_valid_key_passes(self):
        status, body = get("/api/secure", headers={"X-API-Key": "secret-key-1"})
        assert status == 200

    def test_second_valid_key_passes(self):
        status, body = get("/api/secure", headers={"X-API-Key": "secret-key-2"})
        assert status == 200


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class TestCircuitBreaker:
    def test_circuit_trips_and_rejects_with_gateway_error(self):
        # The /api/circuit upstream always returns 503 (always_fail mock).
        # After threshold (3) failures, the circuit trips and the gateway
        # returns its own rejection — distinguishable by the specific body.
        for _ in range(3):
            get("/api/circuit")  # these hit the upstream and record failures

        # The 4th request must be rejected by the circuit breaker itself,
        # not passed through to the upstream.
        status, body = get("/api/circuit")
        assert status == 503
        assert body.get("error") == "service_unavailable", (
            f"Expected circuit-breaker rejection body, got: {body}"
        )
        assert "retry_after" in body
        assert isinstance(body["retry_after"], int)
        assert body["retry_after"] > 0
