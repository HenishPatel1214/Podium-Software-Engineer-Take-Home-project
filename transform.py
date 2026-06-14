import json
import time


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _resolve_value(val: str, request_time: str, response_time: str | None, route_path: str, body_json: dict | None):
    """Resolve dynamic template strings like $request_time, $literal:foo, $body, $route_path."""
    if val == "$request_time":
        return request_time
    if val == "$response_time":
        return response_time or _now_iso()
    if val == "$route_path":
        return route_path
    if val == "$body":
        return body_json
    if val.startswith("$literal:"):
        return val[len("$literal:"):]
    return val


def _dot_get(obj: dict, path: str):
    """Get a nested value from a dict using dot notation: 'user.id' -> obj['user']['id']."""
    parts = path.split(".")
    for part in parts:
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def _dot_set(obj: dict, path: str, value):
    """Set a nested value in a dict using dot notation."""
    parts = path.split(".")
    for part in parts[:-1]:
        obj = obj.setdefault(part, {})
    obj[parts[-1]] = value


def apply_request_transform(cfg, headers: dict, body: bytes | None, request_time: str) -> tuple[dict, bytes | None]:
    headers = dict(headers)

    for k, v in cfg.headers_add.items():
        headers[k] = _resolve_value(str(v), request_time, None, "", None)

    for k in cfg.headers_remove:
        headers.pop(k, None)

    if cfg.body_mapping and body:
        try:
            src = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            src = {}

        dst = {}
        for dest_path, source_key in cfg.body_mapping.items():
            if isinstance(source_key, str) and source_key.startswith("$"):
                value = _resolve_value(source_key, request_time, None, "", src)
            else:
                value = _dot_get(src, source_key)
            _dot_set(dst, dest_path, value)

        body = json.dumps(dst).encode()
        headers["Content-Length"] = str(len(body))
        headers.setdefault("Content-Type", "application/json")

    return headers, body


def apply_response_transform(cfg, headers: dict, body: bytes, route_path: str, request_time: str) -> tuple[dict, bytes]:
    response_time = _now_iso()
    headers = dict(headers)

    for k, v in cfg.headers_add.items():
        headers[k] = _resolve_value(str(v), request_time, response_time, route_path, None)

    for k in cfg.headers_remove:
        headers.pop(k, None)

    if cfg.body_envelope:
        try:
            parsed_body = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed_body = body.decode(errors="replace")

        envelope = {}
        for key, val in cfg.body_envelope.items():
            if isinstance(val, str):
                envelope[key] = _resolve_value(val, request_time, response_time, route_path, parsed_body)
            elif isinstance(val, dict):
                resolved = {}
                for sub_key, sub_val in val.items():
                    resolved[sub_key] = _resolve_value(str(sub_val), request_time, response_time, route_path, parsed_body)
                envelope[key] = resolved
            else:
                envelope[key] = val

        body = json.dumps(envelope).encode()
        headers["Content-Length"] = str(len(body))
        headers["Content-Type"] = "application/json"

    return headers, body
