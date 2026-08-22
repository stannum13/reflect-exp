from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import urllib.request
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from reflect._source_http import _RejectRedirect
from reflect.source_fetch import (
    CacheStore,
    CachingTransport,
    GitHubIdentity,
    GitRunner,
    HttpResponse,
    SourceFetchError,
    UrllibTransport,
    atomic_write_lock,
    lock_yaml_bytes,
    parse_ls_remote,
    resolve_entry,
    resolve_registry,
)
from reflect.sources import (
    LicenseStatus,
    LockedEntry,
    MetadataStatus,
    PathStatus,
    RegistryEntry,
    ReuseMode,
    SourceLock,
    SourceRegistry,
    load_lock,
)
from reflect.safety import SafetyViolation
from scripts.fetch_reference import main as fetch_main


FIXTURES = Path(__file__).parent / "fixtures" / "source_metadata"
COMMIT_SHA = "a" * 40
TREE_SHA = "b" * 40
LICENSE_SHA = "c" * 40
NOW = datetime(2026, 8, 22, 10, 11, 12, tzinfo=timezone.utc)
REPO_URL = "https://github.com/example/project"
COMMIT_URL = f"https://api.github.com/repos/example/project/git/commits/{COMMIT_SHA}"
TREE_URL = f"https://api.github.com/repos/example/project/git/trees/{TREE_SHA}?recursive=1"
ROOT_TREE_URL = f"https://api.github.com/repos/example/project/git/trees/{TREE_SHA}"
LICENSE_URL = f"https://api.github.com/repos/example/project/license?ref={COMMIT_SHA}"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _clock() -> datetime:
    return NOW


def _entry(*paths: str, mode: ReuseMode = ReuseMode.SPARSE_REFERENCE) -> RegistryEntry:
    return RegistryEntry(
        name="example",
        url=REPO_URL,
        mode=mode,
        experiments=("01_test",),
        selected_paths=paths,
        use="Offline fixture.",
    )


class FixtureTransport:
    def __init__(
        self,
        *,
        tree: bytes | None = None,
        license_response: bytes | HttpResponse | None = None,
        extra: dict[str, bytes | HttpResponse] | None = None,
        ls_remote: str | None = None,
    ) -> None:
        self.responses: dict[str, bytes | HttpResponse] = {
            COMMIT_URL: _fixture("github-repository.json"),
            TREE_URL: tree or _fixture("github-tree.json"),
            LICENSE_URL: license_response or _fixture("github-license.json"),
        }
        self.responses.update(extra or {})
        self.ls_remote = ls_remote or (
            f"{COMMIT_SHA}\tHEAD\nref: refs/heads/main\tHEAD\n"
        )
        self.git_calls: list[str] = []
        self.http_calls: list[str] = []

    def run_ls_remote(self, url: str) -> str:
        self.git_calls.append(url)
        return self.ls_remote

    def get(self, url: str) -> HttpResponse:
        self.http_calls.append(url)
        result = self.responses[url]
        if isinstance(result, HttpResponse):
            return result
        return HttpResponse(url=url, status=200, headers={}, body=result)


def _registry(*entries: RegistryEntry) -> SourceRegistry:
    return SourceRegistry(
        verified_at="2026-08-22",
        large_model_downloads_default=False,
        physical_deployment_default=False,
        repositories=entries,
        registry_sha256="9" * 64,
    )


def test_github_identity_rejects_noncanonical_repository_urls() -> None:
    assert GitHubIdentity.from_url(REPO_URL) == GitHubIdentity("example", "project")
    for url in (
        "http://github.com/example/project",
        "https://user@github.com/example/project",
        "https://github.com/example/project/extra",
        "https://github.com/example/project?ref=main",
        "https://github.com/example/project#readme",
        "https://api.github.com/example/project",
    ):
        with pytest.raises(SourceFetchError, match="canonical GitHub"):
            GitHubIdentity.from_url(url)

    with pytest.raises(SourceFetchError, match="canonical GitHub"):
        GitHubIdentity.from_url("https://github.com:malformed/example/project")


def test_ls_remote_parsing_is_order_independent_and_accepts_branch_slashes() -> None:
    output = (
        f"{COMMIT_SHA}\tHEAD\n"
        f"{'d' * 40}\trefs/heads/other\n"
        "ref: refs/heads/release/v2\tHEAD\n"
    )
    assert parse_ls_remote(output) == ("release/v2", COMMIT_SHA)


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("", "symbolic HEAD"),
        (f"{COMMIT_SHA}\tHEAD\n", "symbolic HEAD"),
        ("ref: refs/heads/main\tHEAD\n", "HEAD SHA"),
        (f"ref: refs/tags/v1\tHEAD\n{COMMIT_SHA}\tHEAD\n", "symbolic HEAD"),
        (f"ref: refs/heads/bad branch\tHEAD\n{COMMIT_SHA}\tHEAD\n", "malformed"),
        (f"ref: refs/heads/bad./branch\tHEAD\n{COMMIT_SHA}\tHEAD\n", "malformed"),
        (f"ref: refs/heads/main\tHEAD\n{'a' * 64}\tHEAD\n", "40-character"),
        (
            "ref: refs/heads/main\tHEAD\n"
            "ref: refs/heads/trunk\tHEAD\n"
            f"{COMMIT_SHA}\tHEAD\n",
            "exactly one symbolic HEAD",
        ),
        (
            "ref: refs/heads/main\tHEAD\n"
            f"{COMMIT_SHA}\tHEAD\n{'d' * 40}\tHEAD\n",
            "exactly one HEAD SHA",
        ),
    ],
)
def test_ls_remote_rejects_missing_detached_unborn_malformed_and_duplicate_head(
    output: str, message: str
) -> None:
    with pytest.raises(SourceFetchError, match=message):
        parse_ls_remote(output)


def test_git_runner_uses_fixed_arguments_and_isolated_noninteractive_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured.update(kwargs)
        captured["cwd_entries"] = tuple(Path(kwargs["cwd"]).iterdir())
        return subprocess.CompletedProcess(args, 0, f"ref: refs/heads/main\tHEAD\n{COMMIT_SHA}\tHEAD\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("GIT_ASKPASS", "steal")
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.invalid")
    monkeypatch.setenv("GIT_TRACE", "1")

    output = GitRunner(timeout=7).run_ls_remote(REPO_URL)

    assert COMMIT_SHA in output
    assert captured["args"] == [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "http.followRedirects=false",
        "-c",
        "http.proxy=",
        "-c",
        "https.proxy=",
        "ls-remote",
        "--symref",
        REPO_URL,
        "HEAD",
    ]
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == 7
    assert captured["check"] is False
    assert captured["cwd_entries"] == ()
    environment = captured["env"]
    assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert environment["GIT_CONFIG_SYSTEM"] == "/dev/null"
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_CEILING_DIRECTORIES"] == captured["cwd"]
    assert environment["GIT_DISCOVERY_ACROSS_FILESYSTEM"] == "0"
    assert "GIT_ASKPASS" not in environment
    assert "HTTPS_PROXY" not in environment
    assert "GIT_TRACE" not in environment


def test_git_runner_real_process_ignores_hostile_repository_and_ambient_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "hostile-remote.git"
    (remote / "refs" / "heads").mkdir(parents=True)
    (remote / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (remote / "refs" / "heads" / "main").write_text(f"{COMMIT_SHA}\n", encoding="ascii")
    (remote / "config").write_text("[core]\n\tbare = true\n", encoding="ascii")
    hostile = tmp_path / "hostile-worktree"
    (hostile / ".git").mkdir(parents=True)
    (hostile / ".git" / "config").write_text(
        f'[url "file://{remote}"]\n\tinsteadOf = {REPO_URL}\n', encoding="utf-8"
    )
    binary = tmp_path / "bin"
    binary.mkdir()
    shim = binary / "git"
    shim.write_text(
        "#!/bin/sh\nexec /usr/bin/git -c protocol.https.allow=never \"$@\"\n",
        encoding="ascii",
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GIT_DIR", str(hostile / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(hostile))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.file://{remote}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", REPO_URL)

    with pytest.raises(SourceFetchError, match="git ls-remote failed"):
        GitRunner(timeout=5).run_ls_remote(REPO_URL)


def test_git_runner_reports_failure_without_stderr_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 23, "", "token=secret")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SourceFetchError, match="return code 23") as failure:
        GitRunner().run_ls_remote(REPO_URL)
    assert "secret" not in str(failure.value)


def test_urllib_transport_rejects_redirected_final_url() -> None:
    class Response:
        status = 200
        headers = {"content-length": "2"}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return f"https://api.github.com/repos/evil/project/git/commits/{COMMIT_SHA}"

        def read(self, size: int) -> bytes:
            return b"{}"

    class Opener:
        def open(self, request: object, timeout: float) -> Response:
            return Response()

    with pytest.raises(SourceFetchError, match="redirected outside"):
        UrllibTransport(opener=Opener()).get(COMMIT_URL)


def test_default_http_redirect_policy_refuses_to_follow_response_location() -> None:
    handler = _RejectRedirect()
    with pytest.raises(SourceFetchError, match="redirect"):
        handler.redirect_request(
            object(),
            object(),
            302,
            "Found",
            {},
            "https://evil.invalid/collect",
        )


def test_default_http_transport_disables_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: tuple[object, ...] = ()

    def fake_build_opener(*handlers: object) -> object:
        nonlocal captured
        captured = handlers
        return object()

    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.invalid")
    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    UrllibTransport()
    proxy = next(handler for handler in captured if isinstance(handler, urllib.request.ProxyHandler))
    assert proxy.proxies == {}


def test_resolver_uses_commit_tree_sha_and_exact_evidence_urls() -> None:
    transport = FixtureTransport()
    locked = resolve_entry(_entry("src/example", "README.md", "missing"), transport, _clock)

    assert locked.default_branch == "main"
    assert locked.commit_sha == COMMIT_SHA
    assert locked.retrieved_at == "2026-08-22T10:11:12Z"
    assert locked.metadata_status is MetadataStatus.RESOLVED
    assert locked.metadata_evidence == {
        "commit": COMMIT_URL,
        "ls_remote": f"git ls-remote --symref {REPO_URL} HEAD",
        "tree": TREE_URL,
    }
    assert locked.path_statuses == {
        "src/example": PathStatus.EXISTS,
        "README.md": PathStatus.EXISTS,
        "missing": PathStatus.MISSING,
    }
    assert locked.path_evidence_urls == {
        "src/example": TREE_URL,
        "README.md": TREE_URL,
        "missing": TREE_URL,
    }
    assert transport.http_calls == [COMMIT_URL, TREE_URL, LICENSE_URL]


def test_literal_tree_prefix_and_root_glob_matching_preserve_requested_strings() -> None:
    locked = resolve_entry(_entry("src", "*.py", "src/*.py"), FixtureTransport(), _clock)
    assert locked.path_statuses == {
        "src": PathStatus.EXISTS,
        "*.py": PathStatus.EXISTS,
        "src/*.py": PathStatus.MISSING,
    }


def test_gitlink_is_accepted_as_exact_path_but_not_traversed() -> None:
    locked = resolve_entry(
        _entry("vendor/dependency", "vendor/dependency/README.md"),
        FixtureTransport(),
        _clock,
    )
    assert locked.path_statuses == {
        "vendor/dependency": PathStatus.EXISTS,
        "vendor/dependency/README.md": PathStatus.MISSING,
    }


def test_pinned_repository_license_is_discovered_with_exact_tree_identity() -> None:
    locked = resolve_entry(_entry("README.md"), FixtureTransport(), _clock)
    assert locked.license_status is LicenseStatus.DISCOVERED
    assert locked.license_spdx == "MIT"
    assert locked.license_evidence_url == LICENSE_URL


def _license_response(
    *, spdx: object = "MIT", path: object = "LICENSE", sha: object = LICENSE_SHA
) -> bytes:
    return json.dumps(
        {
            "name": "MIT License",
            "path": path,
            "sha": sha,
            "type": "file",
            "license": {
                "key": "mit",
                "name": "MIT License",
                "spdx_id": spdx,
                "url": "https://api.github.com/licenses/mit",
            },
        }
    ).encode()


def test_license_noassertion_and_malformed_metadata_remain_unknown() -> None:
    for response in (
        _license_response(spdx="NOASSERTION"),
        _license_response(spdx=""),
        _license_response(spdx=None),
        json.dumps({"license": "MIT"}).encode(),
    ):
        locked = resolve_entry(
            _entry("README.md"), FixtureTransport(license_response=response), _clock
        )
        assert locked.license_status is LicenseStatus.UNKNOWN
        assert locked.license_spdx is None
        assert locked.license_evidence_url == LICENSE_URL


@pytest.mark.parametrize(
    "response",
    [
        _license_response(path="COPYING"),
        _license_response(sha="d" * 40),
    ],
)
def test_license_path_or_sha_conflict_with_pinned_tree_remains_unknown(
    response: bytes,
) -> None:
    locked = resolve_entry(
        _entry("README.md"), FixtureTransport(license_response=response), _clock
    )
    assert locked.license_status is LicenseStatus.UNKNOWN
    assert locked.license_spdx is None


def test_multiple_suffix_license_files_remain_ambiguous_unknown() -> None:
    apache_sha = "d" * 40
    mit_sha = "e" * 40
    tree = json.loads(_fixture("github-tree.json"))
    tree["tree"] = [item for item in tree["tree"] if item["path"] != "LICENSE"] + [
        {"path": "LICENSE-MIT", "type": "blob", "sha": mit_sha},
        {"path": "LICENSE-APACHE", "type": "blob", "sha": apache_sha},
    ]
    transport = FixtureTransport(
        tree=json.dumps(tree).encode(),
        license_response=_license_response(path="LICENSE-MIT", sha=mit_sha),
    )
    locked = resolve_entry(_entry("README.md"), transport, _clock)
    assert locked.license_status is LicenseStatus.UNKNOWN
    assert locked.license_spdx is None
    assert transport.http_calls[-1] == LICENSE_URL


def test_absent_repository_license_response_is_unknown() -> None:
    absent = HttpResponse(url=LICENSE_URL, status=404, headers={}, body=b"not found")
    locked = resolve_entry(
        _entry("README.md"), FixtureTransport(license_response=absent), _clock
    )
    assert locked.license_status is LicenseStatus.UNKNOWN
    assert locked.license_spdx is None
    assert locked.license_evidence_url == LICENSE_URL


def test_absent_root_license_is_unknown_with_license_api_evidence() -> None:
    tree = json.loads(_fixture("github-tree.json"))
    tree["tree"] = [item for item in tree["tree"] if item["path"] != "LICENSE"]
    locked = resolve_entry(
        _entry("README.md"), FixtureTransport(tree=json.dumps(tree).encode()), _clock
    )
    assert locked.license_status is LicenseStatus.UNKNOWN
    assert locked.license_spdx is None
    assert locked.license_evidence_url == LICENSE_URL


def test_truncated_tree_walks_only_requested_prefixes_and_root_license() -> None:
    truncated = json.dumps({"sha": TREE_SHA, "truncated": True, "tree": []}).encode()
    root = json.dumps(
        {
            "sha": TREE_SHA,
            "truncated": False,
            "tree": [
                {"path": "src", "type": "tree", "sha": "f" * 40},
                {"path": "LICENSE", "type": "blob", "sha": LICENSE_SHA},
                {"path": "root.py", "type": "blob", "sha": "e" * 40},
            ],
        }
    ).encode()
    src_url = f"https://api.github.com/repos/example/project/git/trees/{'f' * 40}"
    src = json.dumps(
        {
            "sha": "f" * 40,
            "truncated": False,
            "tree": [
                {"path": "example", "type": "tree", "sha": "1" * 40},
            ],
        }
    ).encode()
    transport = FixtureTransport(
        tree=truncated,
        extra={ROOT_TREE_URL: root, src_url: src},
    )

    locked = resolve_entry(_entry("src/example", "*.py", "absent/deep"), transport, _clock)

    assert locked.path_statuses == {
        "src/example": PathStatus.EXISTS,
        "*.py": PathStatus.EXISTS,
        "absent/deep": PathStatus.MISSING,
    }
    assert locked.path_evidence_urls == {
        "src/example": src_url,
        "*.py": ROOT_TREE_URL,
        "absent/deep": ROOT_TREE_URL,
    }
    assert transport.http_calls == [
        COMMIT_URL,
        TREE_URL,
        ROOT_TREE_URL,
        src_url,
        LICENSE_URL,
    ]


def test_truncated_targeted_walk_rejects_another_truncated_tree() -> None:
    truncated = json.dumps({"sha": TREE_SHA, "truncated": True, "tree": []}).encode()
    transport = FixtureTransport(tree=truncated, extra={ROOT_TREE_URL: truncated})
    with pytest.raises(SourceFetchError, match="targeted tree response is truncated"):
        resolve_entry(_entry("src/example"), transport, _clock)


def test_commit_response_must_match_resolved_commit() -> None:
    wrong = json.dumps({"sha": "d" * 40, "tree": {"sha": TREE_SHA}}).encode()
    transport = FixtureTransport(extra={COMMIT_URL: wrong})
    with pytest.raises(SourceFetchError, match="commit SHA does not match"):
        resolve_entry(_entry("README.md"), transport, _clock)


def test_rate_limit_error_reports_reset_without_body_secrets() -> None:
    limited = HttpResponse(
        url=COMMIT_URL,
        status=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1787395200"},
        body=b"token=secret",
    )
    transport = FixtureTransport(extra={COMMIT_URL: limited})
    with pytest.raises(SourceFetchError, match="rate limit.*1787395200") as failure:
        resolve_entry(_entry("README.md"), transport, _clock)
    assert "secret" not in str(failure.value)


def test_cache_validates_endpoint_and_payload_checksum(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path)
    cache.write(
        "example",
        "commit",
        endpoint=COMMIT_URL,
        payload=b"payload",
        retrieved_at="2026-08-22T10:11:12Z",
        etag='"fixture"',
    )
    evidence = cache.load("example", "commit", endpoint=COMMIT_URL)
    assert evidence is not None
    assert evidence.payload == b"payload"
    assert evidence.endpoint == COMMIT_URL
    assert evidence.etag == '"fixture"'
    assert evidence.sha256 == "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5"

    (tmp_path / "example" / "commit.payload").write_bytes(b"tampered")
    assert cache.load("example", "commit", endpoint=COMMIT_URL) is None
    assert cache.load("example", "commit", endpoint=TREE_URL) is None


def test_cache_rejects_dot_path_components(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path)
    with pytest.raises(SourceFetchError, match="safe path component"):
        cache.write(
            "..",
            "commit",
            endpoint=COMMIT_URL,
            payload=b"payload",
            retrieved_at="2026-08-22T10:11:12Z",
        )


def test_caching_transport_uses_one_valid_cache_fallback_after_live_failure(
    tmp_path: Path,
) -> None:
    cache = CacheStore(tmp_path)
    cache.write(
        "example",
        "commit",
        endpoint=COMMIT_URL,
        payload=_fixture("github-repository.json"),
        retrieved_at="2026-08-22T10:11:12Z",
    )

    class Runner:
        def run_ls_remote(self, url: str) -> str:
            raise AssertionError("not used")

    class FailingHttp:
        calls = 0

        def get(self, url: str) -> HttpResponse:
            self.calls += 1
            raise SourceFetchError("live network failure")

    http = FailingHttp()
    transport = CachingTransport(Runner(), http, cache, _clock, "example")
    response = transport.get(COMMIT_URL)
    assert response.body == _fixture("github-repository.json")
    assert http.calls == 1


def test_rate_limit_response_stops_current_invocation_even_with_valid_cache(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path)
    for key, endpoint, payload in (
        ("commit", COMMIT_URL, _fixture("github-repository.json")),
        (f"tree-recursive-{TREE_SHA}", TREE_URL, _fixture("github-tree.json")),
        (f"license-{COMMIT_SHA}", LICENSE_URL, _fixture("github-license.json")),
    ):
        cache.write(
            "example",
            key,
            endpoint=endpoint,
            payload=payload,
            retrieved_at="2026-08-22T10:11:12Z",
        )

    class Runner:
        def run_ls_remote(self, url: str) -> str:
            return f"ref: refs/heads/main\tHEAD\n{COMMIT_SHA}\tHEAD\n"

    class LimitedThenFixture:
        calls: list[str] = []

        def get(self, url: str) -> HttpResponse:
            self.calls.append(url)
            if url == COMMIT_URL:
                return HttpResponse(
                    url=url,
                    status=403,
                    headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1787395200"},
                    body=b"limited",
                )
            raise AssertionError("active rate-limit resume must not issue another HTTP call")

    transport = CachingTransport(Runner(), LimitedThenFixture(), cache, _clock, "example")
    with pytest.raises(SourceFetchError, match="rate limit.*1787395200"):
        resolve_entry(_entry("README.md"), transport, _clock)
    assert LimitedThenFixture.calls == [COMMIT_URL]


@pytest.mark.parametrize("status", [200, 429])
def test_rate_limit_persists_reset_stops_calls_and_later_invocation_resumes(
    tmp_path: Path, status: int
) -> None:
    cache = CacheStore(tmp_path)
    cached = (
        ("ls-remote", f"git ls-remote --symref {REPO_URL} HEAD", f"ref: refs/heads/main\tHEAD\n{COMMIT_SHA}\tHEAD\n".encode()),
        ("commit", COMMIT_URL, _fixture("github-repository.json")),
        (f"tree-recursive-{TREE_SHA}", TREE_URL, _fixture("github-tree.json")),
        (f"license-{COMMIT_SHA}", LICENSE_URL, _fixture("github-license.json")),
    )
    for key, endpoint, payload in cached:
        cache.write("example", key, endpoint=endpoint, payload=payload, retrieved_at="2026-08-22T10:11:12Z")

    class Runner:
        calls = 0
        def run_ls_remote(self, url: str) -> str:
            self.calls += 1
            return cached[0][2].decode()

    class Limited:
        calls: list[str] = []
        def get(self, url: str) -> HttpResponse:
            self.calls.append(url)
            headers = {"x-ratelimit-reset": "1787395200"}
            if status == 200:
                headers["x-ratelimit-remaining"] = "0"
            return HttpResponse(
                url=url,
                status=status,
                headers=headers,
                body=b"limited",
            )

    first = CachingTransport(Runner(), Limited(), cache, _clock, "example")
    with pytest.raises(SourceFetchError, match="rate limit"):
        resolve_entry(_entry("README.md"), first, _clock)
    assert Limited.calls == [COMMIT_URL]
    assert cache.active_rate_limit(_clock) == "1787395200"

    class NoHttp:
        def get(self, url: str) -> HttpResponse:
            raise AssertionError("later rate-limited invocation must stay offline")

    later = CachingTransport(Runner(), NoHttp(), cache, _clock, "example")
    locked = resolve_entry(_entry("README.md"), later, _clock)
    assert locked.metadata_status is MetadataStatus.RESOLVED


@pytest.mark.parametrize("reset", [None, "malformed"])
def test_http_429_without_valid_reset_aborts_even_with_cache(
    tmp_path: Path, reset: str | None
) -> None:
    cache = CacheStore(tmp_path)
    cache.write(
        "example",
        "commit",
        endpoint=COMMIT_URL,
        payload=_fixture("github-repository.json"),
        retrieved_at="2026-08-22T10:11:12Z",
    )

    class Limited:
        calls: list[str] = []

        def get(self, url: str) -> HttpResponse:
            self.calls.append(url)
            headers = {} if reset is None else {"x-ratelimit-reset": reset}
            return HttpResponse(url=url, status=429, headers=headers, body=b"secret")

    live = Limited()
    transport = CachingTransport(FixtureTransport(), live, cache, _clock, "example")
    with pytest.raises(SourceFetchError, match="rate limit.*reset unknown") as failure:
        transport.get(COMMIT_URL)
    with pytest.raises(SourceFetchError, match="rate limit"):
        transport.get(TREE_URL)
    assert live.calls == [COMMIT_URL]
    assert cache.active_rate_limit(_clock) is None
    assert "secret" not in str(failure.value)


def test_active_rate_limit_cache_miss_makes_no_http_call(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path)
    cache.record_rate_limit("1787395200")

    class NoHttp:
        calls = 0
        def get(self, url: str) -> HttpResponse:
            self.calls += 1
            raise AssertionError("HTTP must not be called")

    http = NoHttp()
    transport = CachingTransport(FixtureTransport(), http, cache, _clock, "example")
    with pytest.raises(SourceFetchError, match="rate limit remains active"):
        transport.get(COMMIT_URL)
    assert http.calls == 0


def test_cache_rejects_symlinked_root_and_repository_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SourceFetchError, match="cache directory"):
        CacheStore(root_link).write(
            "example", "commit", endpoint=COMMIT_URL, payload=b"secret", retrieved_at="now"
        )
    assert not (outside / "example").exists()

    root = tmp_path / "cache"
    root.mkdir()
    (root / "example").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SourceFetchError, match="cache directory"):
        CacheStore(root).write(
            "example", "commit", endpoint=COMMIT_URL, payload=b"secret", retrieved_at="now"
        )
    assert not (outside / "commit.payload").exists()


def test_cache_does_not_read_outside_payload_through_symlink(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    repository = root / "example"
    repository.mkdir(parents=True)
    outside = tmp_path / "outside.payload"
    outside.write_bytes(b"outside secret")
    (repository / "commit.payload").symlink_to(outside)
    (repository / "commit.json").write_text(
        json.dumps(
            {
                "endpoint": COMMIT_URL,
                "etag": None,
                "retrieved_at": "now",
                "sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SourceFetchError, match="regular file"):
        CacheStore(root).load("example", "commit", endpoint=COMMIT_URL)


def test_cache_rejects_repository_swap_before_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cache"
    outside = tmp_path / "outside"
    outside.mkdir()
    cache = CacheStore(root)
    real_fsync = os.fsync
    swapped = False

    def swap_before_directory_validation(descriptor: int) -> None:
        nonlocal swapped
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISREG(mode) and not swapped:
            swapped = True
            (root / "example").rename(root / "original-example")
            (root / "example").symlink_to(outside, target_is_directory=True)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", swap_before_directory_validation)
    with pytest.raises(SourceFetchError, match="changed during operation"):
        cache.write(
            "example", "commit", endpoint=COMMIT_URL, payload=b"secret", retrieved_at="now"
        )
    assert not (outside / "commit.payload").exists()


def test_rate_limit_marker_rejects_symlinked_cache_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "cache"
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SourceFetchError, match="cache directory"):
        CacheStore(root).record_rate_limit("1787395200")
    assert not (outside / ".rate-limit.json").exists()


def test_resolve_registry_uses_exact_selectors_and_registry_order() -> None:
    second = RegistryEntry(
        name="second",
        url=REPO_URL,
        mode=ReuseMode.SPARSE_REFERENCE,
        experiments=("01_test",),
        selected_paths=("README.md",),
        use="Second alias fixture.",
    )
    registry = _registry(_entry("README.md"), second)
    lock = resolve_registry(registry, ("second", "example"), FixtureTransport(), _clock)
    assert [entry.name for entry in lock.entries] == ["example", "second"]
    with pytest.raises(SourceFetchError, match="unknown source selector"):
        resolve_registry(registry, ("missing",), FixtureTransport(), _clock)
    with pytest.raises(SourceFetchError, match="duplicate source selector"):
        resolve_registry(registry, ("example", "example"), FixtureTransport(), _clock)


def _locked_entry() -> LockedEntry:
    return LockedEntry(
        name="example",
        url=REPO_URL,
        default_branch="main",
        commit_sha=COMMIT_SHA,
        retrieved_at="2026-08-22T10:11:12Z",
        metadata_evidence=MappingProxyType(
            {
                "tree": TREE_URL,
                "commit": COMMIT_URL,
                "ls_remote": f"git ls-remote --symref {REPO_URL} HEAD",
            }
        ),
        license_spdx="MIT",
        license_status=LicenseStatus.DISCOVERED,
        license_evidence_url=LICENSE_URL,
        path_statuses=MappingProxyType(
            {"README.md": "EXISTS", "missing": "MISSING"}
        ),
        path_evidence_urls=MappingProxyType(
            {"README.md": TREE_URL, "missing": TREE_URL}
        ),
        metadata_status=MetadataStatus.RESOLVED,
    )


def test_lock_yaml_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    lock = SourceLock(
        registry_sha256="9" * 64,
        generated_at="2026-08-22T10:11:12Z",
        entries=(_locked_entry(),),
    )
    first = lock_yaml_bytes(lock)
    second = lock_yaml_bytes(lock)
    assert first == second
    assert first.endswith(b"\n")
    assert yaml.safe_load(first)["entries"][0]["metadata_evidence"] == {
        "commit": COMMIT_URL,
        "ls_remote": f"git ls-remote --symref {REPO_URL} HEAD",
        "tree": TREE_URL,
    }
    path = tmp_path / "repos.lock.yaml"
    path.write_bytes(first)
    assert load_lock(path) == lock


def test_atomic_write_lock_replaces_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "repos.lock.yaml"
    path.write_bytes(b"previous\n")
    lock = SourceLock("9" * 64, "2026-08-22T10:11:12Z", (_locked_entry(),))
    atomic_write_lock(path, lock)
    assert path.read_bytes() == lock_yaml_bytes(lock)
    assert not list(tmp_path.glob(".repos.lock.yaml.*"))


def test_failed_atomic_publication_preserves_existing_lock_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "repos.lock.yaml"
    path.write_bytes(b"previous\n")
    lock = SourceLock("9" * 64, "2026-08-22T10:11:12Z", (_locked_entry(),))

    def fail_replace(source: object, target: object, **kwargs: object) -> None:
        raise OSError("publication failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(SourceFetchError, match="publish source lock"):
        atomic_write_lock(path, lock)
    assert path.read_bytes() == b"previous\n"
    assert not list(tmp_path.glob(".repos.lock.yaml.*"))


def test_metadata_resolution_does_not_create_checkout(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path / "external" / ".metadata")
    transport = CachingTransport(
        FixtureTransport(), FixtureTransport(), cache, _clock, "example"
    )
    locked = resolve_entry(_entry("README.md"), transport, _clock)
    assert locked.metadata_status is MetadataStatus.RESOLVED
    assert not (tmp_path / "external" / "example").exists()
    assert (tmp_path / "external" / ".metadata" / "example").is_dir()


def _write_cli_registry(tmp_path: Path) -> Path:
    path = tmp_path / "repos.yaml"
    path.write_text(
        f'''verified_at: "2026-08-22"
large_model_downloads_default: false
physical_deployment_default: false
repositories:
  - name: example
    url: {REPO_URL}
    mode: SPARSE_REFERENCE
    experiments: [00_source_audit]
    selected_paths: [README.md]
    use: Offline command fixture.
''',
        encoding="utf-8",
    )
    return path


def test_cli_requires_simulation_safety_before_registry_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHYSICAL_DEPLOYMENT_ALLOWED", "true")
    with pytest.raises(SafetyViolation, match="physical deployment"):
        fetch_main(
            ["--name", "example", "--metadata-only"],
            root=tmp_path,
            registry_path=tmp_path / "missing.yaml",
            resolution_transport=FixtureTransport(),
            clock=_clock,
        )


def test_single_name_cli_prints_deterministic_yaml_without_publishing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path = _write_cli_registry(tmp_path)
    lock_path = tmp_path / "repos.lock.yaml"
    lock_path.write_bytes(b"previous bytes\n")
    result = fetch_main(
        ["--name", "example", "--metadata-only"],
        root=tmp_path,
        registry_path=registry_path,
        lock_path=lock_path,
        resolution_transport=FixtureTransport(),
        clock=_clock,
    )
    output = capsys.readouterr().out.encode()
    assert result == 0
    assert yaml.safe_load(output)["entries"][0]["name"] == "example"
    assert lock_path.read_bytes() == b"previous bytes\n"


def test_cli_rejects_partial_update_lock_and_preserves_bytes(tmp_path: Path) -> None:
    registry_path = _write_cli_registry(tmp_path)
    lock_path = tmp_path / "repos.lock.yaml"
    lock_path.write_bytes(b"previous bytes\n")
    with pytest.raises(SystemExit):
        fetch_main(
            ["--name", "example", "--metadata-only", "--update-lock"],
            root=tmp_path,
            registry_path=registry_path,
            lock_path=lock_path,
            resolution_transport=FixtureTransport(),
            clock=_clock,
        )
    assert lock_path.read_bytes() == b"previous bytes\n"


def test_all_metadata_cli_atomically_publishes_complete_candidate(tmp_path: Path) -> None:
    registry_path = _write_cli_registry(tmp_path)
    lock_path = tmp_path / "repos.lock.yaml"
    result = fetch_main(
        ["--all-metadata-only"],
        root=tmp_path,
        registry_path=registry_path,
        lock_path=lock_path,
        resolution_transport=FixtureTransport(),
        clock=_clock,
    )
    assert result == 0
    assert load_lock(lock_path).entries[0].name == "example"


def test_failed_resolution_preserves_existing_lock(tmp_path: Path) -> None:
    registry_path = _write_cli_registry(tmp_path)
    lock_path = tmp_path / "repos.lock.yaml"
    lock_path.write_bytes(b"previous\n")
    limited = HttpResponse(
        url=COMMIT_URL,
        status=429,
        headers={},
        body=b"limited",
    )
    transport = FixtureTransport(extra={COMMIT_URL: limited})
    with pytest.raises(SourceFetchError, match="rate limit"):
        fetch_main(
            ["--all-metadata-only"],
            root=tmp_path,
            registry_path=registry_path,
            lock_path=lock_path,
            resolution_transport=transport,
            clock=_clock,
        )
    assert lock_path.read_bytes() == b"previous\n"
    assert transport.http_calls == [COMMIT_URL]
