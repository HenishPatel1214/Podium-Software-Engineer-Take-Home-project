"""
Start the gateway server and mock upstreams once for the entire test session.
"""
import sys
import os
import threading
import time
import textwrap
import tempfile

import pytest

# Put the assessment directory on the path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mock_server import start_mock_server
from config import load_config
from main import ThreadingHTTPServer, build_handler_class

GATEWAY_PORT = 18080
UPSTREAM_PORT = 19001
SLOW_PORT = 19002
FLAKY_PORT = 19003
AUTH_PORT = 19004
ALWAYS_FAIL_PORT = 19005


def _write_test_config(tmp_path: str) -> str:
    config_content = textwrap.dedent(f"""
        gateway:
          port: {GATEWAY_PORT}
          global_timeout: "3s"
          global_rate_limit:
            requests: 1000
            window: "60s"
            strategy: "fixed_window"
            per: "ip"

        routes:
          - path: "/api/echo"
            methods: ["GET", "POST"]
            strip_prefix: false
            upstream:
              url: "http://127.0.0.1:{UPSTREAM_PORT}"

          - path: "/api/rl-test"
            methods: ["GET"]
            strip_prefix: false
            upstream:
              url: "http://127.0.0.1:{UPSTREAM_PORT}"
            rate_limit:
              requests: 5
              window: "60s"
              strategy: "fixed_window"
              per: "ip"

          - path: "/api/get-only"
            methods: ["GET"]
            strip_prefix: false
            upstream:
              url: "http://127.0.0.1:{UPSTREAM_PORT}"

          - path: "/api/strip"
            methods: ["GET"]
            strip_prefix: true
            upstream:
              url: "http://127.0.0.1:{UPSTREAM_PORT}"

          - path: "/api/slow"
            methods: ["GET"]
            strip_prefix: false
            upstream:
              url: "http://127.0.0.1:{SLOW_PORT}"
              timeout: "1s"

          - path: "/api/retry"
            methods: ["GET"]
            strip_prefix: false
            upstream:
              url: "http://127.0.0.1:{FLAKY_PORT}"
            retry:
              attempts: 3
              backoff: "fixed"
              initial_delay: "0.1s"
              on: [503]

          - path: "/api/transform"
            methods: ["GET", "POST"]
            strip_prefix: false
            upstream:
              url: "http://127.0.0.1:{UPSTREAM_PORT}"
            request_transform:
              headers:
                add:
                  X-Gateway: "gatewaykit"
                remove: ["X-Remove-Me"]
            response_transform:
              headers:
                add:
                  X-Served-By: "gatewaykit"
                remove: ["Server"]
              body:
                envelope:
                  data: "$body"
                  gateway_metadata:
                    route: "$route_path"

          - path: "/api/secure"
            methods: ["GET"]
            strip_prefix: false
            upstream:
              url: "http://127.0.0.1:{AUTH_PORT}"
            auth:
              type: "api_key"
              header: "X-API-Key"
              keys: ["secret-key-1", "secret-key-2"]

          - path: "/api/circuit"
            methods: ["GET"]
            strip_prefix: false
            upstream:
              url: "http://127.0.0.1:{ALWAYS_FAIL_PORT}"
            circuit_breaker:
              threshold: 3
              window: "60s"
              cooldown: "30s"
    """)
    path = os.path.join(tmp_path, "test_gateway.yaml")
    with open(path, "w") as f:
        f.write(config_content)
    return path


@pytest.fixture(scope="session", autouse=True)
def start_servers():
    tmp = tempfile.mkdtemp()
    config_path = _write_test_config(tmp)

    # Start mock upstreams
    start_mock_server(UPSTREAM_PORT, "normal")
    start_mock_server(SLOW_PORT, "slow")
    start_mock_server(FLAKY_PORT, "flaky")
    start_mock_server(AUTH_PORT, "normal")
    start_mock_server(ALWAYS_FAIL_PORT, "always_fail")

    # Start the gateway
    config = load_config(config_path)
    handler = build_handler_class(config)
    server = ThreadingHTTPServer(("127.0.0.1", GATEWAY_PORT), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    time.sleep(0.2)  # give servers time to bind

    yield

    server.shutdown()
