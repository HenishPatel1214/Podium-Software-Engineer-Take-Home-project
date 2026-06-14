import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import proxy
import transform
from circuit_breaker import CircuitBreakerState
from config import Config, Route, config_from_env_or_arg
from load_balancer import LoadBalancer
from rate_limiter import RateLimiter

START_TIME = time.time()


def _find_route(config: Config, path: str) -> Route | None:
    """
    Match incoming path to a configured route.
    Exact prefix match — longer paths like /api/users/123 still match /api/users.
    Returns the first matching route, or None.
    """
    for route in config.routes:
        if path == route.path or path.startswith(route.path + "/") or path.startswith(route.path + "?"):
            return route
    return None


def _get_client_ip(handler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.client_address[0]


def _rate_limit_key(route: Route, ip: str) -> str:
    rl = route.rate_limit
    if rl.per == "global":
        return f"global:{route.path}"
    return f"ip:{ip}:{route.path}"


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class GatewayHandler(BaseHTTPRequestHandler):
    config: Config = None
    rate_limiter: RateLimiter = None
    circuit_breakers: dict = {}
    load_balancers: dict = {}

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_request(self):
        # Health endpoint is always available
        if self.path == "/health" or self.path.startswith("/health?"):
            uptime = int(time.time() - START_TIME)
            self.send_json(200, {"status": "healthy", "uptime_seconds": uptime})
            return

        route = _find_route(self.config, self.path)
        if route is None:
            self.send_json(404, {"error": "not found"})
            return

        if self.command not in route.methods:
            self.send_json(405, {"error": "method not allowed"})
            return

        # Auth check
        if route.auth and route.auth.type == "api_key":
            provided = self.headers.get(route.auth.header, "")
            if provided not in route.auth.keys:
                self.send_json(401, {"error": "unauthorized"})
                return

        # Rate limiting — route-level overrides global
        rl_config = route.rate_limit or self.config.global_rate_limit
        if rl_config:
            ip = _get_client_ip(self)
            key = _rate_limit_key(route, ip) if route.rate_limit else f"ip:{ip}:{route.path}"
            if not self.rate_limiter.is_allowed(key, rl_config):
                self.send_json(429, {"error": "rate limit exceeded"})
                return

        # Circuit breaker check
        cb = self.circuit_breakers.get(route.path)
        if cb:
            is_open, remaining = cb.is_open()
            if is_open:
                self.send_json(503, {"error": "service_unavailable", "retry_after": int(remaining) + 1})
                return

        # Build upstream URL
        lb = self.load_balancers.get(route.path)
        target_base = lb.next_target() if lb else route.upstream.targets[0].url

        upstream_path = self.path
        if route.strip_prefix:
            upstream_path = self.path[len(route.path):]
            if not upstream_path or upstream_path[0] not in ("/", "?"):
                upstream_path = "/" + upstream_path.lstrip("/")

        upstream_url = target_base.rstrip("/") + upstream_path

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Apply request transforms
        request_time = transform._now_iso()
        headers = dict(self.headers)
        if route.request_transform:
            headers, body = transform.apply_request_transform(
                route.request_transform, headers, body, request_time
            )

        # Determine timeout
        timeout = route.upstream.timeout or self.config.global_timeout

        # Proxy with optional retry
        status, resp_headers, resp_body = self._proxy_with_retry(
            upstream_url, headers, body, timeout, route, cb
        )

        # Apply response transforms
        if route.response_transform:
            resp_headers, resp_body = transform.apply_response_transform(
                route.response_transform, resp_headers, resp_body, route.path, request_time
            )

        # Send response
        self.send_response(status)
        skip_headers = {"transfer-encoding", "connection"}
        for k, v in resp_headers.items():
            if k.lower() not in skip_headers:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def _proxy_with_retry(self, url, headers, body, timeout, route, cb):
        retry = route.retry
        attempts = retry.attempts if retry else 1
        delay = retry.initial_delay if retry else 0

        for attempt in range(attempts):
            try:
                status, resp_headers, resp_body = proxy.forward(
                    self.command, url, headers, body, timeout
                )

                if retry and status in retry.on and attempt < attempts - 1:
                    # This status code triggers a retry
                    if cb:
                        cb.record_failure()
                    time.sleep(delay)
                    if retry.backoff == "exponential":
                        delay *= 2
                    continue

                # Success path
                if cb:
                    if status >= 500:
                        cb.record_failure()
                    else:
                        cb.record_success()

                return status, resp_headers, resp_body

            except (ConnectionError, TimeoutError) as e:
                if cb:
                    cb.record_failure()
                if attempt < attempts - 1:
                    time.sleep(delay)
                    if retry and retry.backoff == "exponential":
                        delay *= 2
                    continue
                # All attempts exhausted
                error_msg = "gateway timeout" if isinstance(e, TimeoutError) else "bad gateway"
                code = 504 if isinstance(e, TimeoutError) else 502
                return code, {}, json.dumps({"error": error_msg}).encode()

        return 502, {}, json.dumps({"error": "bad gateway"}).encode()

    # Map all HTTP methods to handle_request
    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()
    def do_PUT(self): self.handle_request()
    def do_DELETE(self): self.handle_request()
    def do_PATCH(self): self.handle_request()
    def do_HEAD(self): self.handle_request()
    def do_OPTIONS(self): self.handle_request()


def build_handler_class(config: Config):
    """Inject config and stateful objects into the handler before the server starts."""
    rate_limiter = RateLimiter()

    circuit_breakers = {}
    for route in config.routes:
        if route.circuit_breaker:
            circuit_breakers[route.path] = CircuitBreakerState(route.circuit_breaker)

    load_balancers = {}
    for route in config.routes:
        if len(route.upstream.targets) > 1:
            load_balancers[route.path] = LoadBalancer(
                route.upstream.targets, route.upstream.balance
            )

    class Handler(GatewayHandler):
        pass

    Handler.config = config
    Handler.rate_limiter = rate_limiter
    Handler.circuit_breakers = circuit_breakers
    Handler.load_balancers = load_balancers

    return Handler


def run():
    config = config_from_env_or_arg()
    handler_class = build_handler_class(config)

    server = ThreadingHTTPServer(("0.0.0.0", config.port), handler_class)
    print(f"GatewayKit running on port {config.port}")
    print(f"Routes: {[r.path for r in config.routes]}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    run()
