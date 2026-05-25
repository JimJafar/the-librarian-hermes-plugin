"""Minimal MCP client for the Librarian HTTP server.

The Librarian's ``/mcp`` is **stateless** JSON-RPC 2.0: no ``initialize``
handshake and no session id are required — a ``tools/call`` can be POSTed
directly with a Bearer token. So this is a single-request client: build the
envelope, POST it, map every failure mode onto a typed
:class:`LibrarianClientError`, and return the tool's text content.

Dependency-light: stdlib ``urllib`` only. The bearer token is sent in the
``Authorization`` header and is NEVER included in any error message or repr.
The transport is injectable so tests never touch the network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal, Protocol

# Cap the body we buffer + parse so a hostile/runaway endpoint can't OOM the host.
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

ClientErrorKind = Literal["network", "timeout", "http", "rpc", "malformed"]


class LibrarianClientError(Exception):
    """A Librarian MCP call failed. Carries a typed ``kind`` so callers can
    fail-soft (log + degrade) without leaking the token."""

    def __init__(self, kind: ClientErrorKind, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.kind: ClientErrorKind = kind
        self.status: int | None = status


class Transport(Protocol):
    def __call__(
        self, url: str, body: bytes, headers: dict[str, str], timeout_s: float
    ) -> tuple[int, bytes]:
        """POST and return ``(status, body)``. Raise ``TimeoutError`` on timeout
        and ``OSError`` on a network failure."""
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow 3xx. urllib's redirect handler carries the Authorization
    header across hosts, which would leak the bearer token to a redirect target.
    The Librarian /mcp is a single stateless POST — it has no legitimate 3xx — so
    a redirect surfaces as an HTTPError (→ a typed `http` error) instead."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


# Opener with redirects disabled. The endpoint scheme is allowlisted in
# LibrarianClient.__init__, so File/Data/FTP handlers can never be reached.
_OPENER = urllib.request.build_opener(_NoRedirect)


def _read_capped(fp: object) -> bytes:
    raw: bytes = fp.read(_MAX_RESPONSE_BYTES + 1)  # type: ignore[attr-defined]
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise OSError("Librarian response exceeded the size cap")
    return raw


def _urllib_transport(
    url: str, body: bytes, headers: dict[str, str], timeout_s: float
) -> tuple[int, bytes]:
    # noqa: S310 — scheme is allowlisted in LibrarianClient.__init__ (http/https
    # only) and redirects are disabled, so file:/custom schemes can't be reached.
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with _OPENER.open(request, timeout=timeout_s) as response:
            return response.status, _read_capped(response)
    except urllib.error.HTTPError as err:
        # A 4xx/5xx (or a refused 3xx) is a real response — surface its status.
        return err.code, _read_capped(err)
    except TimeoutError:
        raise
    except urllib.error.URLError as err:
        if isinstance(err.reason, TimeoutError):
            raise TimeoutError(str(err.reason)) from err
        raise OSError(str(err.reason)) from err


class LibrarianClient:
    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        timeout_ms: int = 15000,
        transport: Transport | None = None,
    ) -> None:
        # Allowlist the scheme so a mistemplated endpoint can't reach urllib's
        # file://, data://, or ftp:// handlers (config-driven SSRF / file read).
        scheme = urllib.parse.urlsplit(endpoint).scheme
        if scheme not in ("https", "http"):
            raise ValueError(f"Librarian endpoint must be http(s), got {scheme!r}")
        self._endpoint = endpoint
        self._token = token
        self._timeout_s = timeout_ms / 1000
        self._transport: Transport = transport or _urllib_transport

    def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        """Call a Librarian MCP tool and return its text content. Raises
        :class:`LibrarianClientError` (typed) on any failure."""
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        ).encode("utf-8")
        # Token only ever lives in this header — never in args, URL, or errors.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

        try:
            status, raw = self._transport(self._endpoint, body, headers, self._timeout_s)
        except TimeoutError as err:
            raise LibrarianClientError(
                "timeout", f"{name} timed out after {self._timeout_s}s"
            ) from err
        except OSError as err:
            # Don't interpolate the wrapped error text into our message — keep the
            # token-bearing request strictly out of anything we render. The cause
            # chain still carries the original for debugging.
            raise LibrarianClientError(
                "network", f"{name} could not reach the Librarian at {self._endpoint}"
            ) from err

        if status != 200:
            raise LibrarianClientError("http", f"{name} returned HTTP {status}", status=status)

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise LibrarianClientError("malformed", f"{name} returned non-JSON") from err

        if isinstance(payload, dict) and "error" in payload:
            rpc = payload["error"]
            code = rpc.get("code") if isinstance(rpc, dict) else None
            raw_msg = rpc.get("message", "") if isinstance(rpc, dict) else ""
            # Truncate the server-controlled message so it can't bloat logs.
            msg = str(raw_msg)[:200]
            raise LibrarianClientError("rpc", f"{name} failed: {msg} (code {code})")

        text = _extract_text(payload)
        if text is None:
            raise LibrarianClientError("malformed", f"{name} response had no text content")
        return text


def _extract_text(payload: object) -> str | None:
    """Pull ``result.content[0].text`` from an MCP tool response, or None."""
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return None
    first = content[0]
    if not isinstance(first, dict):
        return None
    text = first.get("text")
    return text if isinstance(text, str) else None
