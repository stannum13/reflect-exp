"""Pinned, bounded sparse Git checkouts for approved source references."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import select
import selectors
import socket
import stat
import subprocess
import threading
import time
from typing import Any, Protocol
from urllib.parse import urlsplit

from reflect._rollout_io import FileIdentity, cleanup_exact_directory, open_directory_at
from reflect.source_evidence import open_directory_chain
from reflect.sources import (
    PathStatus,
    ReuseMode,
    SourceLock,
    SourceRegistry,
    validate_lock,
)


_ELIGIBLE_EXPERIMENTS = frozenset(
    {"01_policy_control", "02_action_chunks", "03_recovery"}
)
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_MAX_DISK_BYTES = 512 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_GIT_TIMEOUT = 600.0
_CONTAINED_SYMLINK_POLICY = "CONTAINED_GIT_SYMLINKS_V1"


class SparseCheckoutError(RuntimeError):
    """Raised when a sparse source checkout cannot be proven safe and pinned."""

    def __init__(
        self,
        message: str,
        *,
        commands: Sequence[Sequence[str]] = (),
        statuses: Sequence[int] = (),
        download_bytes: int = 0,
    ) -> None:
        super().__init__(message)
        self.commands = tuple(tuple(command) for command in commands)
        self.statuses = tuple(statuses)
        self.download_bytes = download_bytes


@dataclass(frozen=True)
class ContainedGitSymlink:
    path: str
    link_blob_sha1: str
    target: str
    target_path: str
    target_blob_sha1: str


@dataclass(frozen=True)
class ContainedGitSymlinkAudit:
    path: str
    link_blob_sha1: str
    link_bytes: int
    link_sha256: str
    target: str
    target_path: str
    target_blob_sha1: str
    target_bytes: int
    target_sha256: str


@dataclass(frozen=True)
class CheckoutSpec:
    registry_sha256: str
    name: str
    url: str
    commit_sha: str
    requested_paths: tuple[str, ...]
    patterns: tuple[str, ...]
    symlink_policy: str = "REJECT_ALL"
    recursive_tree_sha: str | None = None
    contained_symlinks: tuple[ContainedGitSymlink, ...] = ()


@dataclass(frozen=True)
class CheckoutCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    download_bytes: int
    executed_argv: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckoutResult:
    name: str
    destination: Path
    commit_sha: str
    patterns: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    statuses: tuple[int, ...]
    download_bytes: int
    disk_bytes: int
    content_hashes: Mapping[str, str]
    reused: bool
    destination_identity: tuple[int, int]
    symlink_policy: str = "REJECT_ALL"
    recursive_tree_sha: str | None = None
    contained_symlinks: tuple[ContainedGitSymlinkAudit, ...] = ()


class CheckoutRunner(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        input_bytes: bytes | None = None,
        max_download_bytes: int = _MAX_DOWNLOAD_BYTES,
    ) -> CheckoutCommandResult: ...


def _json_object_no_duplicates(data: bytes) -> Mapping[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SparseCheckoutError(f"duplicate symlink-contract key: {key}")
            result[key] = value
        return result

    try:
        raw = json.loads(data, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SparseCheckoutError("contained-symlink contract is not strict JSON") from exc
    if not isinstance(raw, Mapping):
        raise SparseCheckoutError("contained-symlink contract root must be an object")
    return raw


def apply_contained_symlink_contract(
    spec: CheckoutSpec,
    contract_path: Path,
    expected_sha256: str,
) -> CheckoutSpec:
    """Bind one exact checkout spec to a create-time, hash-sealed link contract."""
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise SparseCheckoutError("contained-symlink contract SHA-256 is invalid")
    try:
        parent = open_directory_chain(contract_path.parent, create=False)
        try:
            descriptor = os.open(
                contract_path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
        finally:
            os.close(parent)
        try:
            value = os.fstat(descriptor)
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_size > 64 * 1024:
                raise SparseCheckoutError("contained-symlink contract must be one bounded regular file")
            data = os.read(descriptor, value.st_size + 1)
            if len(data) != value.st_size:
                raise SparseCheckoutError("contained-symlink contract changed during read")
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise SparseCheckoutError("contained-symlink contract path is unsafe") from exc
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise SparseCheckoutError("contained-symlink contract SHA-256 does not match")
    raw = _json_object_no_duplicates(data)
    keys = {
        "schema_version", "policy", "registry_sha256", "repository", "url",
        "commit_sha", "recursive_tree_sha", "symlinks",
    }
    if set(raw) != keys or raw["schema_version"] != 1 or raw["policy"] != _CONTAINED_SYMLINK_POLICY:
        raise SparseCheckoutError("contained-symlink contract schema or policy is invalid")
    if (
        raw["registry_sha256"] != spec.registry_sha256
        or raw["repository"] != spec.name
        or raw["url"] != spec.url
        or raw["commit_sha"] != spec.commit_sha
        or _SHA40.fullmatch(raw["recursive_tree_sha"] if type(raw["recursive_tree_sha"]) is str else "") is None
    ):
        raise SparseCheckoutError("contained-symlink contract does not bind checkout identity")
    if not isinstance(raw["symlinks"], list):
        raise SparseCheckoutError("contained-symlink contract rows must be a list")
    row_keys = {"path", "link_blob_sha1", "target", "target_path", "target_blob_sha1"}
    rows = []
    for row in raw["symlinks"]:
        if not isinstance(row, Mapping) or set(row) != row_keys:
            raise SparseCheckoutError("contained-symlink contract row schema is invalid")
        item = ContainedGitSymlink(**row)
        _validate_pattern(item.path)
        _validate_pattern(item.target_path)
        if _SHA40.fullmatch(item.link_blob_sha1) is None or _SHA40.fullmatch(item.target_blob_sha1) is None:
            raise SparseCheckoutError("contained-symlink contract blob identity is invalid")
        if _normalized_link_target(item.path, item.target) != item.target_path:
            raise SparseCheckoutError("contained-symlink contract target does not normalize exactly")
        rows.append(item)
    if not rows or len({item.path for item in rows}) != len(rows):
        raise SparseCheckoutError("contained-symlink contract rows must be nonempty and unique")
    return replace(
        spec,
        symlink_policy=_CONTAINED_SYMLINK_POLICY,
        recursive_tree_sha=raw["recursive_tree_sha"],
        contained_symlinks=tuple(rows),
    )


class _ConnectTunnel:
    """One-purpose loopback CONNECT tunnel with an upstream-to-client byte cap."""

    def __init__(self, host: str, port: int, cap: int) -> None:
        self.host = host
        self.port = port
        self.cap = cap
        self.consumed = 0
        self.capped = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._sockets: set[socket.socket] = set()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(4)
        self._listener.settimeout(0.1)
        self.local_port = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._accept, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _track(self, value: socket.socket) -> None:
        with self._lock:
            self._sockets.add(value)

    def _untrack(self, value: socket.socket) -> None:
        with self._lock:
            self._sockets.discard(value)

    def _accept(self) -> None:
        while not self._stop.is_set() and not self.capped.is_set():
            try:
                client, address = self._listener.accept()
            except (TimeoutError, OSError):
                continue
            if address[0] != "127.0.0.1":
                client.close()
                continue
            self._track(client)
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            client.settimeout(5)
            request = bytearray()
            while b"\r\n\r\n" not in request and len(request) <= 8192:
                chunk = client.recv(1024)
                if not chunk:
                    return
                request.extend(chunk)
            first = bytes(request).split(b"\r\n", 1)[0]
            expected = f"CONNECT {self.host}:{self.port} HTTP/1.1".encode("ascii")
            if first != expected or len(request) > 8192:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return
            upstream = socket.create_connection((self.host, self.port), timeout=5)
            self._track(upstream)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            client.setblocking(False)
            upstream.setblocking(False)
            while not self._stop.is_set() and not self.capped.is_set():
                readable, _, _ = select.select((client, upstream), (), (), 0.05)
                for source in readable:
                    try:
                        data = source.recv(64 * 1024)
                    except BlockingIOError:
                        continue
                    if not data:
                        return
                    if source is upstream:
                        with self._lock:
                            remaining = self.cap - self.consumed
                            accepted = data[: max(0, remaining + 1)]
                            self.consumed += len(accepted)
                            over = self.consumed > self.cap
                        if accepted:
                            client.sendall(accepted)
                        if over:
                            self.capped.set()
                            return
                    else:
                        upstream.sendall(data)
        except OSError:
            return
        finally:
            for value in (client, upstream):
                if value is not None:
                    self._untrack(value)
                    try:
                        value.close()
                    except OSError:
                        pass

    def close(self) -> None:
        self._stop.set()
        try:
            self._listener.close()
        except OSError:
            pass
        with self._lock:
            values = tuple(self._sockets)
        for value in values:
            try:
                value.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                value.close()
            except OSError:
                pass
        self._thread.join(timeout=1)

class SubprocessCheckoutRunner:
    def __init__(self, registry_url: str = "https://github.com/") -> None:
        parsed = urlsplit(registry_url)
        if parsed.scheme != "https" or parsed.hostname is None or parsed.username is not None or parsed.password is not None:
            raise SparseCheckoutError("registry URL cannot define the checkout tunnel")
        self._host = parsed.hostname
        self._port = parsed.port or 443

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        input_bytes: bytes | None = None,
        max_download_bytes: int = _MAX_DOWNLOAD_BYTES,
    ) -> CheckoutCommandResult:
        checkout = None
        if "-C" in argv:
            index = argv.index("-C")
            if index + 1 >= len(argv):
                raise SparseCheckoutError("Git -C argument is missing")
            checkout = cwd / argv[index + 1]
        network_capable = Path(argv[0]).name == "git" and (
            "fetch" in argv or "checkout" in argv
        )
        tunnel = _ConnectTunnel(self._host, self._port, max_download_bytes) if network_capable else None
        executed_argv = argv
        if tunnel is not None:
            tunnel.start()
            executed_argv = (argv[0], "-c", f"http.proxy=http://127.0.0.1:{tunnel.local_port}", *argv[1:])
        process: subprocess.Popen[bytes] | None = None
        poller: selectors.BaseSelector | None = None
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        returncode = 70
        capped = False
        timed_out = False
        try:
            process = subprocess.Popen(
                executed_argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if input_bytes is not None:
                assert process.stdin is not None
                try:
                    process.stdin.write(input_bytes)
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            assert process.stdout is not None and process.stderr is not None
            poller = selectors.DefaultSelector()
            poller.register(process.stdout, selectors.EVENT_READ, "stdout")
            poller.register(process.stderr, selectors.EVENT_READ, "stderr")
            started = time.monotonic()
            while poller.get_map():
                retained = _retained_git_bytes(checkout, strict=False)
                capped = bool(tunnel and tunnel.capped.is_set()) or retained > _MAX_DISK_BYTES
                timed_out = time.monotonic() - started > timeout
                if capped or timed_out:
                    if process.poll() is None:
                        process.kill()
                    break
                events = poller.select(0.01)
                if not events and process.poll() is not None:
                    events = [(key, selectors.EVENT_READ) for key in tuple(poller.get_map().values())]
                for key, _ in events:
                    remaining = 1024 * 1024 - len(captured["stdout"]) - len(captured["stderr"])
                    if remaining < 0:
                        capped = True
                        process.kill()
                        break
                    try:
                        chunk = os.read(key.fileobj.fileno(), min(64 * 1024, remaining + 1))
                    except BlockingIOError:
                        continue
                    if chunk:
                        captured[key.data].extend(chunk)
                    else:
                        poller.unregister(key.fileobj)
            returncode = process.wait()
        except OSError as exc:
            raise SparseCheckoutError(
                f"Git checkout command failed: {type(exc).__name__}",
                commands=(executed_argv,), statuses=(70,),
                download_bytes=tunnel.consumed if tunnel else 0,
            ) from exc
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            if poller is not None:
                poller.close()
            if tunnel is not None:
                tunnel.close()
        if timed_out:
            returncode = 124
        elif capped or (tunnel is not None and tunnel.capped.is_set()):
            returncode = 70
        elif returncode < 0:
            returncode = 128 + abs(returncode)
        return CheckoutCommandResult(
            returncode,
            bytes(captured["stdout"]),
            bytes(captured["stderr"]),
            tunnel.consumed if tunnel else 0,
            executed_argv,
        )


def _retained_git_bytes(checkout: Path | None, *, strict: bool = True) -> int:
    if checkout is None:
        return 0
    git = checkout / ".git"
    try:
        if not git.exists():
            return 0
    except OSError:
        return _MAX_DISK_BYTES + 1
    total = 0
    for current, directories, files in os.walk(git, topdown=True, followlinks=False):
        current_path = Path(current)
        safe = []
        for name in sorted(directories):
            try:
                value = (current_path / name).lstat()
            except OSError:
                if strict:
                    raise
                return _MAX_DISK_BYTES + 1
            if stat.S_ISLNK(value.st_mode):
                if strict:
                    raise SparseCheckoutError("Git metadata contains a symlinked directory")
                return _MAX_DISK_BYTES + 1
            safe.append(name)
        directories[:] = safe
        for name in sorted(files):
            try:
                value = (current_path / name).lstat()
            except OSError:
                if strict:
                    raise
                return _MAX_DISK_BYTES + 1
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                if strict:
                    raise SparseCheckoutError("Git metadata contains a nonregular or linked file")
                return _MAX_DISK_BYTES + 1
            total += max(value.st_size, getattr(value, "st_blocks", 0) * 512)
            if total > _MAX_DOWNLOAD_BYTES:
                if strict:
                    raise SparseCheckoutError("Git metadata exceeded its disk byte ceiling")
                return total
    return total


def _validate_pattern(pattern: str) -> None:
    if (
        type(pattern) is not str
        or not pattern
        or pattern.startswith("/")
        or "\\" in pattern
        or "\0" in pattern
        or "\n" in pattern
        or "\r" in pattern
        or any(part in {"", ".", ".."} for part in PurePosixPath(pattern).parts)
    ):
        raise SparseCheckoutError(f"unsafe selected path: {pattern!r}")


def eligible_checkout_specs(
    registry: SourceRegistry,
    lock: SourceLock,
    *,
    name: str | None = None,
    experiment: str | None = None,
) -> tuple[CheckoutSpec, ...]:
    if (name is None) == (experiment is None):
        raise SparseCheckoutError("exactly one name or experiment selector is required")
    errors = validate_lock(registry, lock, require_complete=True)
    if errors:
        raise SparseCheckoutError(f"complete P2 lock is required: {errors[0]}")
    locked = {entry.name: entry for entry in lock.entries}
    selected = []
    for entry in registry.repositories:
        eligible = entry.mode is ReuseMode.SPARSE_REFERENCE and bool(
            set(entry.experiments) & _ELIGIBLE_EXPERIMENTS
        )
        matches = entry.name == name if name is not None else experiment in entry.experiments
        if not eligible or not matches:
            continue
        pinned = locked[entry.name]
        if pinned.commit_sha is None:
            raise SparseCheckoutError(f"complete locked SHA is missing: {entry.name}")
        for path in entry.selected_paths:
            _validate_pattern(path)
        patterns = tuple(
            path
            for path in entry.selected_paths
            if pinned.path_statuses[path] is PathStatus.EXISTS
        )
        if not patterns:
            raise SparseCheckoutError(
                f"selector includes no eligible existing path: {entry.name}"
            )
        selected.append(
            CheckoutSpec(
                registry.registry_sha256,
                entry.name,
                entry.url,
                pinned.commit_sha,
                entry.selected_paths,
                patterns,
            )
        )
    if not selected:
        raise SparseCheckoutError("selector includes no eligible sparse reference")
    return tuple(selected)


def _environment() -> dict[str, str]:
    blocked = {
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "ssh_askpass",
    }
    result = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") and key.lower() not in blocked
    }
    result.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PROTOCOL_FROM_USER": "0",
        }
    )
    return result


def _inspection_prefix(checkout: str) -> tuple[str, ...]:
    return (
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "credential.helper=",
        "-C",
        checkout,
    )


def _run_checked(
    runner: CheckoutRunner,
    argv: tuple[str, ...],
    *,
    cwd: Path,
    environment: dict[str, str],
    input_bytes: bytes | None = None,
    max_download_bytes: int = _MAX_DOWNLOAD_BYTES,
) -> CheckoutCommandResult:
    result = runner.run(
        argv,
        cwd=cwd,
        env=environment,
        timeout=_GIT_TIMEOUT,
        input_bytes=input_bytes,
        max_download_bytes=max_download_bytes,
    )
    receipt = result.executed_argv or argv
    if type(result.stdout) is not bytes or type(result.stderr) is not bytes:
        raise SparseCheckoutError("Git checkout command output must be bytes", commands=(receipt,), statuses=(70,))
    if type(result.returncode) is not int or result.returncode < 0:
        raise SparseCheckoutError("Git checkout command status is invalid", commands=(receipt,), statuses=(70,))
    if type(result.download_bytes) is not int or result.download_bytes < 0:
        raise SparseCheckoutError("Git checkout download receipt is invalid", commands=(receipt,), statuses=(result.returncode,))
    if result.download_bytes > max_download_bytes:
        raise SparseCheckoutError("Git checkout download exceeded its byte ceiling", commands=(receipt,), statuses=(result.returncode,), download_bytes=result.download_bytes)
    if result.returncode != 0:
        raise SparseCheckoutError(
            f"Git checkout command returned {result.returncode}: {argv[-1]}",
            commands=(receipt,),
            statuses=(result.returncode,),
            download_bytes=result.download_bytes,
        )
    return result


def _directory_identity(descriptor: int) -> tuple[int, int]:
    value = os.fstat(descriptor)
    return value.st_dev, value.st_ino


def _path_matches_root(path: Path, identity: tuple[int, int]) -> bool:
    try:
        value = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(value.st_mode) and (value.st_dev, value.st_ino) == identity


def _git_blob_sha1(content: bytes) -> str:
    header = b"blob " + str(len(content)).encode("ascii") + b"\0"
    return hashlib.sha1(header + content).hexdigest()


def _normalized_link_target(link_path: str, target: str) -> str:
    if (
        type(target) is not str
        or not target
        or target.startswith("/")
        or "\\" in target
        or "\0" in target
        or "\n" in target
        or "\r" in target
    ):
        raise SparseCheckoutError("contained Git symlink target must be relative")
    parts = list(PurePosixPath(link_path).parent.parts)
    for part in PurePosixPath(target).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise SparseCheckoutError("contained Git symlink target escapes locked tree")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise SparseCheckoutError("contained Git symlink target is not a file")
    return PurePosixPath(*parts).as_posix()


def _read_regular_beneath(root: Path, relative: str, label: str) -> bytes:
    _validate_pattern(relative)
    root_descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    descriptor = root_descriptor
    try:
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=descriptor,
            )
            if descriptor != root_descriptor:
                os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=descriptor,
        )
        try:
            before = os.fstat(file_descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise SparseCheckoutError(f"{label} must be a regular descriptor file")
            if before.st_size > _MAX_DISK_BYTES:
                raise SparseCheckoutError(f"{label} exceeds the bounded byte limit")
            content = os.read(file_descriptor, before.st_size + 1)
            after = os.fstat(file_descriptor)
            if len(content) != before.st_size or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise SparseCheckoutError(f"{label} changed during inspection")
            return content
        finally:
            os.close(file_descriptor)
    except (OSError, ValueError) as exc:
        if isinstance(exc, SparseCheckoutError):
            raise
        raise SparseCheckoutError(f"{label} target is missing or unsafe") from exc
    finally:
        if descriptor != root_descriptor:
            os.close(descriptor)
        os.close(root_descriptor)


def audit_contained_git_symlinks(
    checkout: Path,
    contracts: Sequence[ContainedGitSymlink],
    *,
    git_objects: Mapping[str, tuple[str, str, str]],
) -> tuple[ContainedGitSymlinkAudit, ...]:
    """Validate declared Git symlink objects without following filesystem links."""
    if not contracts or len({item.path for item in contracts}) != len(contracts):
        raise SparseCheckoutError("contained Git symlink contract must be nonempty and unique")
    expected_paths = {item.path for item in contracts} | {item.target_path for item in contracts}
    if set(git_objects) != expected_paths:
        raise SparseCheckoutError("contained Git symlink Git inventory is incomplete or extra")
    rows = []
    for item in contracts:
        _validate_pattern(item.path)
        _validate_pattern(item.target_path)
        if _SHA40.fullmatch(item.link_blob_sha1) is None or _SHA40.fullmatch(item.target_blob_sha1) is None:
            raise SparseCheckoutError("contained Git symlink blob identity is invalid")
        normalized = _normalized_link_target(item.path, item.target)
        if normalized != item.target_path:
            raise SparseCheckoutError("contained Git symlink target path does not normalize exactly")
        if git_objects[item.path] != ("120000", "blob", item.link_blob_sha1):
            raise SparseCheckoutError("contained Git symlink object mode or blob differs from contract")
        target_object = git_objects[item.target_path]
        if target_object[0] not in {"100644", "100755"} or target_object[1:] != ("blob", item.target_blob_sha1):
            raise SparseCheckoutError("contained Git symlink target must be one regular locked blob")
        link_content = _read_regular_beneath(checkout, item.path, "contained Git symlink")
        target_content = _read_regular_beneath(checkout, item.target_path, "contained Git symlink target")
        if link_content != item.target.encode("utf-8") or _git_blob_sha1(link_content) != item.link_blob_sha1:
            raise SparseCheckoutError("contained Git symlink descriptor does not match locked blob")
        if _git_blob_sha1(target_content) != item.target_blob_sha1:
            raise SparseCheckoutError("contained Git symlink target content does not match locked blob")
        rows.append(
            ContainedGitSymlinkAudit(
                path=item.path,
                link_blob_sha1=item.link_blob_sha1,
                link_bytes=len(link_content),
                link_sha256=hashlib.sha256(link_content).hexdigest(),
                target=item.target,
                target_path=item.target_path,
                target_blob_sha1=item.target_blob_sha1,
                target_bytes=len(target_content),
                target_sha256=hashlib.sha256(target_content).hexdigest(),
            )
        )
    return tuple(rows)


def _parse_ls_tree(data: bytes) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    for record in data.split(b"\0"):
        if not record:
            continue
        try:
            header, encoded_path = record.split(b"\t", 1)
            mode, kind, digest = header.decode("ascii").split(" ")
            path = encoded_path.decode("utf-8")
        except (UnicodeError, ValueError) as exc:
            raise SparseCheckoutError("Git tree inventory is malformed") from exc
        if path in result:
            raise SparseCheckoutError("Git tree inventory contains duplicate paths")
        result[path] = (mode, kind, digest)
    return result


def _tree_facts(path: Path) -> tuple[int, dict[str, str]]:
    total = 0
    hashes: dict[str, str] = {}
    for current, directories, files in os.walk(path, topdown=True, followlinks=False):
        current_path = Path(current)
        safe_directories = []
        for name in sorted(directories):
            child = current_path / name
            value = child.lstat()
            if stat.S_ISLNK(value.st_mode):
                raise SparseCheckoutError("checkout contains a symlinked directory")
            safe_directories.append(name)
        directories[:] = safe_directories
        for name in sorted(files):
            child = current_path / name
            value = child.lstat()
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                raise SparseCheckoutError("checkout contains a nonregular or linked file")
            relative = child.relative_to(path).as_posix()
            total += max(value.st_size, getattr(value, "st_blocks", 0) * 512)
            if total > _MAX_DISK_BYTES:
                raise SparseCheckoutError("checkout exceeded its disk byte ceiling")
            if ".git" not in PurePosixPath(relative).parts:
                content = child.read_bytes()
                if len(content) != value.st_size:
                    raise SparseCheckoutError("checkout file changed during inspection")
                hashes[relative] = hashlib.sha256(content).hexdigest()
    return total, hashes


def _materialized(path: Path, patterns: Sequence[str]) -> None:
    for pattern in patterns:
        matches = tuple(path.glob(pattern)) if any(char in pattern for char in "*?[") else (path / pattern,)
        if not matches or not any(match.exists() for match in matches):
            raise SparseCheckoutError(f"locked existing path was not materialized: {pattern}")
        for match in matches:
            try:
                match.relative_to(path)
            except ValueError as exc:
                raise SparseCheckoutError("materialized path escaped checkout") from exc
            if match.is_symlink():
                raise SparseCheckoutError("materialized path is symlinked")


def _materialized_patterns(spec: CheckoutSpec) -> tuple[str, ...]:
    if spec.symlink_policy == "REJECT_ALL":
        if spec.recursive_tree_sha is not None or spec.contained_symlinks:
            raise SparseCheckoutError("REJECT_ALL cannot carry a contained-symlink contract")
        return spec.patterns
    if spec.symlink_policy != _CONTAINED_SYMLINK_POLICY:
        raise SparseCheckoutError("checkout symlink policy is invalid")
    if _SHA40.fullmatch(spec.recursive_tree_sha or "") is None:
        raise SparseCheckoutError("contained-symlink policy requires the locked recursive tree")
    target_paths = tuple(item.target_path for item in spec.contained_symlinks)
    if not target_paths or len(set(target_paths)) != len(target_paths):
        raise SparseCheckoutError("contained-symlink target paths must be nonempty and unique")
    return (*spec.patterns, *target_paths)


def _publish_no_replace(root_descriptor: int, source: str, destination: str) -> None:
    if os.uname().sysname == "Darwin":
        name, flag = "renameatx_np", 0x00000004
    else:
        name, flag = "renameat2", 0x00000001
    function = getattr(ctypes.CDLL(None, use_errno=True), name, None)
    if function is None:
        raise SparseCheckoutError("atomic no-replace publication is unavailable")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(root_descriptor, os.fsencode(source), root_descriptor, os.fsencode(destination), flag) == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise SparseCheckoutError("checkout destination already exists")
    raise SparseCheckoutError(f"atomic checkout publication failed: {os.strerror(error)}")


def _cleanup_owned_directory(
    root_descriptor: int,
    name: str,
    identity: tuple[int, int],
) -> None:
    try:
        current = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
    except OSError:
        return
    if identity != (current.st_dev, current.st_ino) or not stat.S_ISDIR(current.st_mode):
        return
    try:
        descriptor, opened_identity = open_directory_at(root_descriptor, name)
    except ValueError:
        return
    try:
        if (opened_identity.device, opened_identity.inode) == identity:
            cleanup_exact_directory(
                root_descriptor,
                descriptor,
                FileIdentity(*identity),
                name,
            )
    finally:
        os.close(descriptor)


def cleanup_new_checkout(result: CheckoutResult) -> None:
    """Remove only a newly published checkout at its retained exact identity."""
    if result.reused:
        return
    try:
        parent = open_directory_chain(result.destination.parent, create=False)
    except (OSError, ValueError):
        return
    try:
        _cleanup_owned_directory(parent, result.destination.name, result.destination_identity)
        os.fsync(parent)
    finally:
        os.close(parent)


def _validate_checkout(
    spec: CheckoutSpec,
    checkout_name: str,
    *,
    root: Path,
    runner: CheckoutRunner,
    environment: dict[str, str],
    download_budget: int = _MAX_DOWNLOAD_BYTES,
) -> tuple[list[tuple[str, ...]], list[int], int, int, dict[str, str], tuple[ContainedGitSymlinkAudit, ...]]:
    commands: list[tuple[str, ...]] = []
    statuses: list[int] = []
    download = 0

    def run(argv: tuple[str, ...]) -> CheckoutCommandResult:
        nonlocal download
        try:
            result = _run_checked(runner, argv, cwd=root, environment=environment, max_download_bytes=download_budget - download)
        except SparseCheckoutError as exc:
            failed_statuses = exc.statuses or tuple(70 for _ in exc.commands)
            raise SparseCheckoutError(
                str(exc),
                commands=(*commands, *exc.commands),
                statuses=(*statuses, *failed_statuses),
                download_bytes=download + exc.download_bytes,
            ) from exc
        except BaseException as exc:
            raise SparseCheckoutError(
                f"checkout runner failed: {type(exc).__name__}",
                commands=(*commands, argv),
                statuses=(*statuses, 70),
                download_bytes=download,
            ) from exc
        commands.append(result.executed_argv or argv)
        statuses.append(result.returncode)
        download += result.download_bytes
        if download > download_budget:
            raise SparseCheckoutError("cumulative Git download exceeded its byte ceiling", commands=commands, statuses=statuses, download_bytes=download)
        return result

    prefix = _inspection_prefix(checkout_name)
    try:
        head = run((*prefix, "rev-parse", "HEAD")).stdout.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise SparseCheckoutError("checkout HEAD output is malformed", commands=commands, statuses=statuses, download_bytes=download) from exc
    if head != spec.commit_sha:
        raise SparseCheckoutError("checkout HEAD does not match locked SHA", commands=commands, statuses=statuses, download_bytes=download)
    status = run((*prefix, "status", "--porcelain=v1", "-z")).stdout
    if status:
        raise SparseCheckoutError("checkout destination is dirty", commands=commands, statuses=statuses, download_bytes=download)
    try:
        listed = run((*prefix, "sparse-checkout", "list")).stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        raise SparseCheckoutError("checkout sparse output is malformed", commands=commands, statuses=statuses, download_bytes=download) from exc
    materialized_patterns = _materialized_patterns(spec)
    if tuple(listed) != materialized_patterns:
        raise SparseCheckoutError("checkout sparse patterns do not match lock", commands=commands, statuses=statuses, download_bytes=download)
    checkout = root / checkout_name
    try:
        _materialized(checkout, spec.patterns)
        audits: tuple[ContainedGitSymlinkAudit, ...] = ()
        if spec.symlink_policy == _CONTAINED_SYMLINK_POLICY:
            tree = run((*prefix, "rev-parse", "HEAD^{tree}")).stdout.decode("ascii", errors="strict").strip()
            if tree != spec.recursive_tree_sha:
                raise SparseCheckoutError("checkout tree does not match locked recursive tree")
            object_paths = tuple(
                path
                for item in spec.contained_symlinks
                for path in (item.path, item.target_path)
            )
            inventory = _parse_ls_tree(
                run((*prefix, "ls-tree", "-z", "HEAD", "--", *object_paths)).stdout
            )
            audits = audit_contained_git_symlinks(
                checkout, spec.contained_symlinks, git_objects=inventory
            )
        disk, hashes = _tree_facts(checkout)
    except SparseCheckoutError as exc:
        raise SparseCheckoutError(
            str(exc), commands=commands, statuses=statuses, download_bytes=download
        ) from exc
    return commands, statuses, download, disk, hashes, audits


def checkout_sparse(
    spec: CheckoutSpec,
    root: Path,
    runner: CheckoutRunner,
) -> CheckoutResult:
    if _SHA40.fullmatch(spec.commit_sha) is None:
        raise SparseCheckoutError("locked SHA must be a 40-character lowercase value")
    _validate_pattern(spec.name)
    for pattern in spec.patterns:
        _validate_pattern(pattern)
    materialized_patterns = _materialized_patterns(spec)
    try:
        root_descriptor = open_directory_chain(root, create=True)
    except (OSError, ValueError) as exc:
        raise SparseCheckoutError("checkout root or intermediate directory is unsafe") from exc
    root_identity = _directory_identity(root_descriptor)
    environment = _environment()
    partial = f".{spec.name}.partial-{os.urandom(8).hex()}"
    partial_created = False
    partial_identity: tuple[int, int] | None = None
    commands: list[tuple[str, ...]] = []
    statuses: list[int] = []
    download = 0
    try:
        existing = os.stat(spec.name, dir_fd=root_descriptor, follow_symlinks=False) if spec.name in os.listdir(root_descriptor) else None
        if existing is not None:
            if not stat.S_ISDIR(existing.st_mode):
                raise SparseCheckoutError("checkout destination is not a safe directory")
            if stat.S_IMODE(existing.st_mode) != 0o700:
                raise SparseCheckoutError("reused checkout directory mode must be 0700")
            commands, statuses, download, disk, hashes, audits = _validate_checkout(
                spec, spec.name, root=root, runner=runner, environment=environment,
                download_budget=_MAX_DOWNLOAD_BYTES,
            )
            if not _path_matches_root(root, root_identity):
                raise SparseCheckoutError("checkout root changed during operation", commands=commands, statuses=statuses, download_bytes=download)
            return CheckoutResult(spec.name, root / spec.name, spec.commit_sha, spec.patterns, tuple(commands), tuple(statuses), download, disk, hashes, True, (existing.st_dev, existing.st_ino), spec.symlink_policy, spec.recursive_tree_sha, audits)

        def run(argv: tuple[str, ...], input_bytes: bytes | None = None) -> None:
            nonlocal download
            try:
                result = _run_checked(
                    runner,
                    argv,
                    cwd=root,
                    environment=environment,
                    input_bytes=input_bytes,
                    max_download_bytes=_MAX_DOWNLOAD_BYTES - download,
                )
            except SparseCheckoutError as exc:
                failed_statuses = exc.statuses or tuple(70 for _ in exc.commands)
                raise SparseCheckoutError(
                    str(exc),
                    commands=(*commands, *exc.commands),
                    statuses=(*statuses, *failed_statuses),
                    download_bytes=download + exc.download_bytes,
                ) from exc
            except BaseException as exc:
                raise SparseCheckoutError(
                    f"checkout runner failed: {type(exc).__name__}",
                    commands=(*commands, argv),
                    statuses=(*statuses, 70),
                    download_bytes=download,
                ) from exc
            commands.append(result.executed_argv or argv)
            statuses.append(result.returncode)
            download += result.download_bytes
            if download > _MAX_DOWNLOAD_BYTES:
                raise SparseCheckoutError("cumulative Git download exceeded its byte ceiling", commands=commands, statuses=statuses, download_bytes=download)
            if not _path_matches_root(root, root_identity):
                raise SparseCheckoutError(
                    "checkout root changed during operation",
                    commands=commands,
                    statuses=statuses,
                    download_bytes=download,
                )

        os.mkdir(partial, 0o700, dir_fd=root_descriptor)
        partial_created = True
        opened = os.open(partial, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_descriptor)
        try:
            os.fchmod(opened, 0o700)
            partial_identity = _directory_identity(opened)
        finally:
            os.close(opened)
        run(("git", "init", "--quiet", partial))
        prefix = _inspection_prefix(partial)
        run((*prefix, "remote", "add", "origin", spec.url))
        run((*prefix, "fetch", "--quiet", "--depth=1", "--filter=blob:none", "origin", spec.commit_sha))
        run((*prefix, "sparse-checkout", "init", "--no-cone"))
        if spec.symlink_policy == _CONTAINED_SYMLINK_POLICY:
            run((*prefix, "config", "core.symlinks", "false"))
        run((*prefix, "sparse-checkout", "set", "--no-cone", "--stdin"), ("\n".join(materialized_patterns) + "\n").encode())
        run((*prefix, "checkout", "--quiet", "--detach", spec.commit_sha))
        checked_commands, checked_statuses, checked_download, disk, hashes, audits = _validate_checkout(
            spec, partial, root=root, runner=runner, environment=environment,
            download_budget=_MAX_DOWNLOAD_BYTES - download,
        )
        commands.extend(checked_commands)
        statuses.extend(checked_statuses)
        download += checked_download
        if download > _MAX_DOWNLOAD_BYTES:
            raise SparseCheckoutError("cumulative Git download exceeded its byte ceiling", commands=commands, statuses=statuses, download_bytes=download)
        if not _path_matches_root(root, root_identity):
            raise SparseCheckoutError("checkout root changed during operation", commands=commands, statuses=statuses, download_bytes=download)
        current = os.stat(partial, dir_fd=root_descriptor, follow_symlinks=False)
        if partial_identity != (current.st_dev, current.st_ino):
            raise SparseCheckoutError("checkout partial directory changed during operation", commands=commands, statuses=statuses, download_bytes=download)
        if stat.S_IMODE(current.st_mode) != 0o700:
            raise SparseCheckoutError("checkout partial directory mode changed from 0700", commands=commands, statuses=statuses, download_bytes=download)
        try:
            _publish_no_replace(root_descriptor, partial, spec.name)
        except SparseCheckoutError as exc:
            raise SparseCheckoutError(str(exc), commands=commands, statuses=statuses, download_bytes=download) from exc
        if not _path_matches_root(root, root_identity):
            _cleanup_owned_directory(root_descriptor, spec.name, partial_identity)
            partial_created = False
            raise SparseCheckoutError("checkout root changed after publication", commands=commands, statuses=statuses, download_bytes=download)
        published = os.stat(spec.name, dir_fd=root_descriptor, follow_symlinks=False)
        if partial_identity != (published.st_dev, published.st_ino) or stat.S_IMODE(published.st_mode) != 0o700:
            _cleanup_owned_directory(root_descriptor, spec.name, partial_identity)
            partial_created = False
            raise SparseCheckoutError("published checkout identity or mode is invalid", commands=commands, statuses=statuses, download_bytes=download)
        partial_created = False
        os.fsync(root_descriptor)
        return CheckoutResult(spec.name, root / spec.name, spec.commit_sha, spec.patterns, tuple(commands), tuple(statuses), download, disk, hashes, False, partial_identity, spec.symlink_policy, spec.recursive_tree_sha, audits)
    except BaseException as exc:
        if partial_created and partial_identity is not None:
            _cleanup_owned_directory(root_descriptor, partial, partial_identity)
        if isinstance(exc, SparseCheckoutError):
            raise
        raise SparseCheckoutError(
            f"checkout operation failed: {type(exc).__name__}",
            commands=commands,
            statuses=statuses,
            download_bytes=download,
        ) from exc
    finally:
        os.close(root_descriptor)
