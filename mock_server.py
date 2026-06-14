"""
Simple mock upstream servers used by tests.
Each server runs in a background daemon thread.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


def _make_handler(behavior: str):
    class MockHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # silence request logs during tests

        def do_GET(self):
            self._handle()

        def do_POST(self):
            self._handle()

        def do_PUT(self):
            self._handle()

        def _handle(self):
            if behavior == "normal":
                self._respond(200, {"message": "ok", "path": self.path})
            elif behavior == "slow":
                time.sleep(2)
                self._respond(200, {"message": "slow response"})
            elif behavior == "flaky":
                # Alternate between 200 and 503
                MockHandler._call_count = getattr(MockHandler, "_call_count", 0) + 1
                if MockHandler._call_count % 2 == 0:
                    self._respond(503, {"error": "temporarily unavailable"})
                else:
                    self._respond(200, {"message": "ok"})
            elif behavior == "always_fail":
                self._respond(503, {"error": "upstream error"})
            elif behavior == "healthz":
                if self.path == "/healthz":
                    self._respond(200, {"status": "ok"})
                else:
                    self._respond(200, {"message": "ok", "path": self.path})

        def _respond(self, status: int, body: dict):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return MockHandler


def start_mock_server(port: int, behavior: str = "normal") -> HTTPServer:
    """Start a mock upstream on the given port and return the server object."""
    server = HTTPServer(("127.0.0.1", port), _make_handler(behavior))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
