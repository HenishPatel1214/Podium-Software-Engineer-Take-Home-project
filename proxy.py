import urllib.request
import urllib.error


def forward(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
    """
    Forward an HTTP request to the upstream URL.

    Returns (status_code, response_headers_dict, response_body_bytes).
    Raises ConnectionError if the upstream is unreachable.
    """
    # Strip hop-by-hop headers that must not be forwarded
    skip = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
             "te", "trailers", "transfer-encoding", "upgrade", "host"}
    safe_headers = {k: v for k, v in headers.items() if k.lower() not in skip}

    req = urllib.request.Request(
        url,
        data=body if body else None,
        headers=safe_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        # HTTPError is still a valid HTTP response from the upstream
        return e.code, dict(e.headers), e.read()
    except urllib.error.URLError as e:
        raise ConnectionError(f"Upstream unreachable: {e.reason}")
    except TimeoutError:
        raise TimeoutError(f"Upstream timed out after {timeout}s")
