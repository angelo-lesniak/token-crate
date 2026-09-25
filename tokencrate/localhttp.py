"""Direct HTTP requests to the local model and browser UI services: one
transport that ignores host proxy settings, and the three request shapes
the wrapper makes (a body or None, a POST's outcome, a probe's decoded
response or stream)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.request import ProxyHandler, build_opener

from . import TokenCrateError

# Host proxy settings apply to downloads, never to loopback API requests.
OPENER = build_opener(ProxyHandler({}))
# The first request of a probe loads the model from disk.
LOAD_TIMEOUT = 900


def http_get(url: str, timeout: float = 5) -> str | None:
    """The body of a GET, or None when the request fails."""
    try:
        with OPENER.open(url, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError, ValueError):
        return None


def http_post(url: str, payload: dict, timeout: float = 5) -> str:
    """POST a JSON body and report what the request did: "" when the router
    accepted it, otherwise what refused it. The caller reads the effect from
    the state that follows; this only explains a state that never changes."""
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    try:
        with OPENER.open(request, timeout=timeout):
            return ""
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}"
    except (OSError, urllib.error.URLError, ValueError) as error:
        return str(error)


def request(url: str, payload: dict | None = None, *, timeout: int = LOAD_TIMEOUT, stream: bool = False):
    """A probe request: the decoded JSON (or text, or None for an empty
    body), the open response with `stream`, and a TokenCrateError that
    names the URL for an HTTP error or an unreachable service."""
    data = None
    headers = {"User-Agent": "TokenCrate-probe/1"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        response = OPENER.open(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        with error:
            body = error.read().decode("utf-8", errors="replace")[:500]
        raise TokenCrateError(f"HTTP {error.code} from {url}: {body}") from error
    except (OSError, urllib.error.URLError) as error:
        raise TokenCrateError(f"could not reach {url}: {error}") from error
    if stream:
        return response
    with response:
        body = response.read().decode("utf-8", errors="replace")
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body
