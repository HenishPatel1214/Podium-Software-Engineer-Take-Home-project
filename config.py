import os
import re
import sys
import yaml
from dataclasses import dataclass, field
from typing import Optional


def parse_duration(s: str) -> float:
    """Convert '30s', '5m', '500ms', '1h' to seconds as a float."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)", s.strip())
    if not match:
        raise ValueError(f"Cannot parse duration: {s!r}")
    value, unit = float(match.group(1)), match.group(2)
    return value * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]


@dataclass
class RateLimit:
    requests: int
    window: float       # seconds
    strategy: str       # "fixed_window" or "sliding_window"
    per: str            # "ip" or "global"


@dataclass
class RetryConfig:
    attempts: int
    backoff: str        # "fixed" or "exponential"
    initial_delay: float
    on: list            # status codes that trigger a retry


@dataclass
class UpstreamTarget:
    url: str
    weight: int = 1


@dataclass
class Upstream:
    targets: list               # list of UpstreamTarget
    balance: str = "round_robin"
    timeout: Optional[float] = None


@dataclass
class RequestTransform:
    headers_add: dict = field(default_factory=dict)
    headers_remove: list = field(default_factory=list)
    body_mapping: dict = field(default_factory=dict)


@dataclass
class ResponseTransform:
    headers_add: dict = field(default_factory=dict)
    headers_remove: list = field(default_factory=list)
    body_envelope: dict = field(default_factory=dict)


@dataclass
class Auth:
    type: str
    header: str
    keys: list


@dataclass
class CircuitBreaker:
    threshold: int
    window: float
    cooldown: float


@dataclass
class Route:
    path: str
    methods: list
    strip_prefix: bool
    upstream: Upstream
    rate_limit: Optional[RateLimit] = None
    retry: Optional[RetryConfig] = None
    request_transform: Optional[RequestTransform] = None
    response_transform: Optional[ResponseTransform] = None
    auth: Optional[Auth] = None
    circuit_breaker: Optional[CircuitBreaker] = None


@dataclass
class Config:
    port: int
    global_timeout: float
    global_rate_limit: Optional[RateLimit]
    routes: list            # list of Route


def _parse_rate_limit(d: dict) -> RateLimit:
    return RateLimit(
        requests=d["requests"],
        window=parse_duration(d["window"]),
        strategy=d.get("strategy", "fixed_window"),
        per=d.get("per", "ip"),
    )


def _parse_upstream(d: dict) -> Upstream:
    if "targets" in d:
        targets = [UpstreamTarget(url=t["url"], weight=t.get("weight", 1)) for t in d["targets"]]
    else:
        targets = [UpstreamTarget(url=d["url"], weight=1)]
    return Upstream(
        targets=targets,
        balance=d.get("balance", "round_robin"),
        timeout=parse_duration(d["timeout"]) if "timeout" in d else None,
    )


def _parse_request_transform(d: dict) -> RequestTransform:
    headers = d.get("headers", {})
    body = d.get("body", {})
    return RequestTransform(
        headers_add=headers.get("add", {}),
        headers_remove=headers.get("remove", []),
        body_mapping=body.get("mapping", {}),
    )


def _parse_response_transform(d: dict) -> ResponseTransform:
    headers = d.get("headers", {})
    body = d.get("body", {})
    return ResponseTransform(
        headers_add=headers.get("add", {}),
        headers_remove=headers.get("remove", []),
        body_envelope=body.get("envelope", {}),
    )


def _parse_route(d: dict) -> Route:
    return Route(
        path=d["path"],
        methods=[m.upper() for m in d["methods"]],
        strip_prefix=d.get("strip_prefix", False),
        upstream=_parse_upstream(d["upstream"]),
        rate_limit=_parse_rate_limit(d["rate_limit"]) if "rate_limit" in d else None,
        retry=RetryConfig(
            attempts=d["retry"]["attempts"],
            backoff=d["retry"].get("backoff", "fixed"),
            initial_delay=parse_duration(d["retry"]["initial_delay"]),
            on=d["retry"].get("on", []),
        ) if "retry" in d else None,
        request_transform=_parse_request_transform(d["request_transform"]) if "request_transform" in d else None,
        response_transform=_parse_response_transform(d["response_transform"]) if "response_transform" in d else None,
        auth=Auth(
            type=d["auth"]["type"],
            header=d["auth"]["header"],
            keys=d["auth"]["keys"],
        ) if "auth" in d else None,
        circuit_breaker=CircuitBreaker(
            threshold=d["circuit_breaker"]["threshold"],
            window=parse_duration(d["circuit_breaker"]["window"]),
            cooldown=parse_duration(d["circuit_breaker"]["cooldown"]),
        ) if "circuit_breaker" in d else None,
    )


def load_config(path: str) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)

    gw = data["gateway"]
    global_rl = _parse_rate_limit(gw["global_rate_limit"]) if "global_rate_limit" in gw else None

    return Config(
        port=gw.get("port", 8080),
        global_timeout=parse_duration(gw.get("global_timeout", "30s")),
        global_rate_limit=global_rl,
        routes=[_parse_route(r) for r in data.get("routes", [])],
    )


def config_from_env_or_arg() -> Config:
    path = None
    if len(sys.argv) > 1:
        path = sys.argv[1]
    elif "GATEWAY_CONFIG" in os.environ:
        path = os.environ["GATEWAY_CONFIG"]

    if not path:
        print("Usage: python main.py <config.yaml>  or  GATEWAY_CONFIG=<path> python main.py")
        sys.exit(1)

    if not os.path.exists(path):
        print(f"Config file not found: {path}")
        sys.exit(1)

    return load_config(path)
