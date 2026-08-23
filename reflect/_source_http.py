"""Bounded, unauthenticated transport for derived GitHub metadata endpoints."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from types import MappingProxyType
from typing import Any, Protocol
import urllib.error
import urllib.parse
import urllib.request


class SourceFetchError(RuntimeError):
    """Raised when source metadata cannot be resolved factually and safely."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]+\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_API_ENDPOINT = re.compile(
    r"https://api\.github\.com/repos/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/"
    r"git/(commits|trees)/([0-9a-f]{40})(\?recursive=1)?\Z"
)
_LICENSE_ENDPOINT = re.compile(
    r"https://api\.github\.com/repos/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/"
    r"license\?ref=([0-9a-f]{40})\Z"
)
_WHEEL_ENDPOINT = re.compile(
    r"https://files\.pythonhosted\.org/packages/[0-9a-f]{2}/[0-9a-f]{2}/"
    r"[0-9a-f]{32,}/[^/?#]+\.whl\Z"
)
_USER_AGENT = "reflect-lite-source-metadata/0.1"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class GitHubIdentity:
    owner: str
    repo: str

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.owner) or not _IDENTIFIER.fullmatch(self.repo):
            raise SourceFetchError("repository URL is not a canonical GitHub identity")

    @classmethod
    def from_url(cls, url: str) -> "GitHubIdentity":
        try:
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise SourceFetchError("repository URL is not a canonical GitHub identity") from exc
        parts = parsed.path.split("/")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or len(parts) != 3
            or parts[0] != ""
            or not _IDENTIFIER.fullmatch(parts[1])
            or not _IDENTIFIER.fullmatch(parts[2])
        ):
            raise SourceFetchError("repository URL is not a canonical GitHub identity")
        return cls(parts[1], parts[2])

    @property
    def repository_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"

    def commit_url(self, sha: str) -> str:
        _require_sha(sha, "commit")
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/git/commits/{sha}"

    def tree_url(self, sha: str, *, recursive: bool) -> str:
        _require_sha(sha, "tree")
        suffix = "?recursive=1" if recursive else ""
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/git/trees/{sha}{suffix}"

    def license_url(self, commit_sha: str) -> str:
        _require_sha(commit_sha, "commit")
        return (
            f"https://api.github.com/repos/{self.owner}/{self.repo}/license"
            f"?ref={commit_sha}"
        )


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if type(self.url) is not str or not self.url:
            raise SourceFetchError("HTTP response URL must be a non-empty string")
        if type(self.status) is not int:
            raise SourceFetchError("HTTP response status must be an integer")
        if not isinstance(self.body, bytes):
            raise SourceFetchError("HTTP response body must be bytes")
        normalized: dict[str, str] = {}
        for key, value in self.headers.items():
            if type(key) is not str or type(value) is not str:
                raise SourceFetchError("HTTP response headers must be strings")
            normalized[key.lower()] = value
        object.__setattr__(self, "headers", MappingProxyType(normalized))


class Transport(Protocol):
    def get(self, url: str) -> HttpResponse: ...


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Any,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        raise SourceFetchError("GitHub response redirect was refused")


def _require_sha(value: object, label: str) -> str:
    if type(value) is not str or not _SHA40.fullmatch(value):
        raise SourceFetchError(f"{label} SHA must be a 40-character lowercase hexadecimal value")
    return value


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SourceFetchError("UTC clock must return a timezone-aware datetime")
    utc = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc.isoformat().replace("+00:00", "Z")


def _validate_api_endpoint(url: str) -> None:
    match = _API_ENDPOINT.fullmatch(url)
    if (
        match is None
        and _LICENSE_ENDPOINT.fullmatch(url) is None
        and _WHEEL_ENDPOINT.fullmatch(url) is None
    ):
        raise SourceFetchError("HTTP endpoint is not an exact allowed metadata object")
    if match is None:
        return
    object_type = match.group(3)
    recursive = match.group(5)
    if recursive and object_type != "trees":
        raise SourceFetchError("recursive query is allowed only for Git tree endpoints")


class UrllibTransport:
    """Use urllib with fixed headers, bounded reads, and exact redirect checks."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        opener: Any | None = None,
    ) -> None:
        if timeout <= 0 or max_response_bytes <= 0:
            raise ValueError("transport bounds must be positive")
        self._timeout = timeout
        self._max_response_bytes = max_response_bytes
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _RejectRedirect()
        )

    def get(self, url: str) -> HttpResponse:
        _validate_api_endpoint(url)
        accept = (
            "application/octet-stream"
            if _WHEEL_ENDPOINT.fullmatch(url) is not None
            else "application/vnd.github+json"
        )
        request = urllib.request.Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": _USER_AGENT,
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                final_url = response.geturl()
                if final_url != url:
                    raise SourceFetchError(
                        f"GitHub response redirected outside the exact derived endpoint: {url}"
                    )
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError as exc:
                        raise SourceFetchError(
                            f"GitHub response has invalid content length: {url}"
                        ) from exc
                    if declared > self._max_response_bytes:
                        raise SourceFetchError(f"GitHub response exceeds size limit: {url}")
                body = response.read(self._max_response_bytes + 1)
                if len(body) > self._max_response_bytes:
                    raise SourceFetchError(f"GitHub response exceeds size limit: {url}")
                return HttpResponse(
                    url=final_url,
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    body=body,
                )
        except urllib.error.HTTPError as exc:
            final_url = exc.geturl()
            if final_url != url:
                raise SourceFetchError(
                    f"GitHub response redirected outside the exact derived endpoint: {url}"
                ) from exc
            body = exc.read(self._max_response_bytes + 1)
            if len(body) > self._max_response_bytes:
                raise SourceFetchError(f"GitHub response exceeds size limit: {url}") from exc
            return HttpResponse(
                url=final_url,
                status=exc.code,
                headers=dict(exc.headers.items()),
                body=body,
            )
        except SourceFetchError:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise SourceFetchError(
                f"GitHub request failed for {url}: {type(exc).__name__}"
            ) from exc


def _validate_response_status(
    response: HttpResponse,
    endpoint: str,
    *,
    allowed_statuses: frozenset[int] = frozenset(),
) -> None:
    if response.url != endpoint:
        raise SourceFetchError(f"GitHub response URL does not match requested endpoint: {endpoint}")
    remaining = response.headers.get("x-ratelimit-remaining")
    raw_reset = response.headers.get("x-ratelimit-reset", "")
    reset = raw_reset if raw_reset.isdecimal() else "unknown"
    if remaining == "0":
        raise SourceFetchError(f"GitHub rate limit exhausted for {endpoint}; reset {reset}")
    if response.status == 429:
        raise SourceFetchError(f"GitHub rate limit response for {endpoint}; reset {reset}")
    if response.status >= 400 and response.status not in allowed_statuses:
        raise SourceFetchError(f"GitHub request failed for {endpoint} with HTTP {response.status}")


def _json_object(response: HttpResponse, endpoint: str) -> dict[str, Any]:
    _validate_response_status(response, endpoint)
    try:
        result = json.loads(response.body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceFetchError(f"GitHub response is not valid JSON: {endpoint}") from exc
    if not isinstance(result, dict):
        raise SourceFetchError(f"GitHub response is not a JSON object: {endpoint}")
    return result
