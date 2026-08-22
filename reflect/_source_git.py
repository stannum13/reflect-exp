"""Strict, configuration-isolated Git HEAD metadata resolution."""

from __future__ import annotations

import os
import subprocess
from typing import Protocol

from reflect._source_http import GitHubIdentity, SourceFetchError, _require_sha


class Runner(Protocol):
    def run_ls_remote(self, url: str) -> str: ...


def _valid_branch(value: str) -> bool:
    forbidden = set(" ~^:?*[\\")
    components = value.split("/")
    return not (
        not value
        or value == "@"
        or value.startswith("/")
        or value.endswith(("/", "."))
        or "//" in value
        or ".." in value
        or "@{" in value
        or any(
            ord(character) < 32
            or ord(character) == 127
            or character in forbidden
            for character in value
        )
        or any(
            component.startswith(".") or component.endswith(".lock")
            for component in components
        )
    )


def parse_ls_remote(output: str) -> tuple[str, str]:
    """Parse exactly one symbolic branch HEAD and one matching full SHA record."""
    if type(output) is not str:
        raise SourceFetchError("git ls-remote output must be text")
    symbolic: list[str] = []
    shas: list[str] = []
    for line in output.splitlines():
        if "\t" not in line:
            continue
        value, refname = line.split("\t", 1)
        if refname != "HEAD":
            continue
        if value.startswith("ref: "):
            target = value[5:]
            prefix = "refs/heads/"
            branch = target[len(prefix) :] if target.startswith(prefix) else ""
            if _valid_branch(branch):
                symbolic.append(branch)
            else:
                raise SourceFetchError("git ls-remote symbolic HEAD is malformed")
        else:
            shas.append(value)
    if len(symbolic) != 1:
        if not symbolic:
            raise SourceFetchError("git ls-remote did not return a symbolic HEAD")
        raise SourceFetchError("git ls-remote must return exactly one symbolic HEAD")
    if len(shas) != 1:
        if not shas:
            raise SourceFetchError("git ls-remote did not return a HEAD SHA")
        raise SourceFetchError("git ls-remote must return exactly one HEAD SHA")
    _require_sha(shas[0], "HEAD")
    return symbolic[0], shas[0]


class GitRunner:
    """Run the one allowed Git metadata command with hostile config disabled."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._timeout = timeout

    def run_ls_remote(self, url: str) -> str:
        identity = GitHubIdentity.from_url(url)
        environment = dict(os.environ)
        blocked_exact = {
            "GIT_ASKPASS",
            "SSH_ASKPASS",
            "GIT_PROXY_COMMAND",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
        }
        blocked_prefixes = (
            "GIT_CONFIG_",
            "GIT_TRACE",
            "GIT_CREDENTIAL",
        )
        blocked_proxy = {
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
        }
        for key in tuple(environment):
            if (
                key in blocked_exact
                or key.startswith(blocked_prefixes)
                or key.lower() in blocked_proxy
            ):
                environment.pop(key, None)
        environment.update(
            {
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        args = ["git", "ls-remote", "--symref", identity.repository_url, "HEAD"]
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceFetchError(
                f"git ls-remote failed for {identity.repository_url}: {type(exc).__name__}"
            ) from exc
        if completed.returncode != 0:
            raise SourceFetchError(
                f"git ls-remote failed for {identity.repository_url} with return code "
                f"{completed.returncode}"
            )
        parse_ls_remote(completed.stdout)
        return completed.stdout
