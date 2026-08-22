"""Pinned, bounded sparse Git checkouts for approved source references."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import ctypes
import errno
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Protocol

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
class CheckoutSpec:
    registry_sha256: str
    name: str
    url: str
    commit_sha: str
    requested_paths: tuple[str, ...]
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class CheckoutCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    download_bytes: int


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


class CheckoutRunner(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        input_bytes: bytes | None = None,
    ) -> CheckoutCommandResult: ...


class SubprocessCheckoutRunner:
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        input_bytes: bytes | None = None,
    ) -> CheckoutCommandResult:
        checkout = None
        if "-C" in argv:
            index = argv.index("-C")
            if index + 1 >= len(argv):
                raise SparseCheckoutError("Git -C argument is missing")
            checkout = cwd / argv[index + 1]
        before = _retained_git_bytes(checkout) if checkout is not None else 0
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SparseCheckoutError(
                f"Git checkout command failed: {type(exc).__name__}"
            ) from exc
        after = _retained_git_bytes(checkout) if checkout is not None else 0
        retained_growth = max(0, after - before)
        network_capable = "fetch" in argv or "checkout" in argv
        # Git exposes no exact transport counter. Pack growth plus a fixed
        # protocol/filesystem allowance is a deterministic conservative receipt.
        accounted_download = (
            retained_growth + 64 * 1024
            if network_capable and retained_growth
            else 0
        )
        return CheckoutCommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
            accounted_download,
        )


def _retained_git_bytes(checkout: Path | None) -> int:
    if checkout is None:
        return 0
    git = checkout / ".git"
    if not git.exists():
        return 0
    total = 0
    for current, directories, files in os.walk(git, topdown=True, followlinks=False):
        current_path = Path(current)
        safe = []
        for name in sorted(directories):
            value = (current_path / name).lstat()
            if stat.S_ISLNK(value.st_mode):
                raise SparseCheckoutError("Git metadata contains a symlinked directory")
            safe.append(name)
        directories[:] = safe
        for name in sorted(files):
            value = (current_path / name).lstat()
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                raise SparseCheckoutError("Git metadata contains a nonregular or linked file")
            total += max(value.st_size, getattr(value, "st_blocks", 0) * 512)
            if total > _MAX_DOWNLOAD_BYTES:
                raise SparseCheckoutError("Git transport accounting exceeded its byte ceiling")
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
) -> CheckoutCommandResult:
    result = runner.run(
        argv,
        cwd=cwd,
        env=environment,
        timeout=_GIT_TIMEOUT,
        input_bytes=input_bytes,
    )
    if type(result.stdout) is not bytes or type(result.stderr) is not bytes:
        raise SparseCheckoutError("Git checkout command output must be bytes", commands=(argv,))
    if type(result.download_bytes) is not int or not 0 <= result.download_bytes <= _MAX_DOWNLOAD_BYTES:
        raise SparseCheckoutError("Git checkout download exceeded its byte ceiling", commands=(argv,))
    if type(result.returncode) is not int or result.returncode < 0:
        raise SparseCheckoutError("Git checkout command status is invalid", commands=(argv,))
    if result.returncode != 0:
        raise SparseCheckoutError(
            f"Git checkout command returned {result.returncode}: {argv[-1]}",
            commands=(argv,),
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


def _validate_checkout(
    spec: CheckoutSpec,
    checkout_name: str,
    *,
    root: Path,
    runner: CheckoutRunner,
    environment: dict[str, str],
) -> tuple[list[tuple[str, ...]], list[int], int, int, dict[str, str]]:
    commands: list[tuple[str, ...]] = []
    statuses: list[int] = []
    download = 0

    def run(argv: tuple[str, ...]) -> CheckoutCommandResult:
        nonlocal download
        try:
            result = _run_checked(runner, argv, cwd=root, environment=environment)
        except SparseCheckoutError as exc:
            raise SparseCheckoutError(
                str(exc),
                commands=(*commands, *exc.commands),
                statuses=(*statuses, *exc.statuses),
                download_bytes=download + exc.download_bytes,
            ) from exc
        commands.append(argv)
        statuses.append(result.returncode)
        download += result.download_bytes
        if download > _MAX_DOWNLOAD_BYTES:
            raise SparseCheckoutError("cumulative Git download exceeded its byte ceiling", commands=commands, statuses=statuses, download_bytes=download)
        return result

    prefix = _inspection_prefix(checkout_name)
    head = run((*prefix, "rev-parse", "HEAD")).stdout.decode("ascii", errors="strict").strip()
    if head != spec.commit_sha:
        raise SparseCheckoutError("checkout HEAD does not match locked SHA", commands=commands, statuses=statuses, download_bytes=download)
    status = run((*prefix, "status", "--porcelain=v1", "-z")).stdout
    if status:
        raise SparseCheckoutError("checkout destination is dirty", commands=commands, statuses=statuses, download_bytes=download)
    listed = run((*prefix, "sparse-checkout", "list")).stdout.decode("utf-8", errors="strict").splitlines()
    if tuple(listed) != spec.patterns:
        raise SparseCheckoutError("checkout sparse patterns do not match lock", commands=commands, statuses=statuses, download_bytes=download)
    checkout = root / checkout_name
    try:
        _materialized(checkout, spec.patterns)
        disk, hashes = _tree_facts(checkout)
    except SparseCheckoutError as exc:
        raise SparseCheckoutError(
            str(exc), commands=commands, statuses=statuses, download_bytes=download
        ) from exc
    return commands, statuses, download, disk, hashes


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
    try:
        root_descriptor = open_directory_chain(root, create=True)
    except (OSError, ValueError) as exc:
        raise SparseCheckoutError("checkout root or intermediate directory is unsafe") from exc
    root_identity = _directory_identity(root_descriptor)
    environment = _environment()
    partial = f".{spec.name}.partial-{os.urandom(8).hex()}"
    partial_created = False
    partial_identity: tuple[int, int] | None = None
    try:
        existing = os.stat(spec.name, dir_fd=root_descriptor, follow_symlinks=False) if spec.name in os.listdir(root_descriptor) else None
        if existing is not None:
            if not stat.S_ISDIR(existing.st_mode):
                raise SparseCheckoutError("checkout destination is not a safe directory")
            commands, statuses, download, disk, hashes = _validate_checkout(
                spec, spec.name, root=root, runner=runner, environment=environment
            )
            if not _path_matches_root(root, root_identity):
                raise SparseCheckoutError("checkout root changed during operation", commands=commands, statuses=statuses, download_bytes=download)
            return CheckoutResult(spec.name, root / spec.name, spec.commit_sha, spec.patterns, tuple(commands), tuple(statuses), download, disk, hashes, True)

        commands: list[tuple[str, ...]] = []
        statuses: list[int] = []
        download = 0

        def run(argv: tuple[str, ...], input_bytes: bytes | None = None) -> None:
            nonlocal download
            try:
                result = _run_checked(
                    runner,
                    argv,
                    cwd=root,
                    environment=environment,
                    input_bytes=input_bytes,
                )
            except SparseCheckoutError as exc:
                raise SparseCheckoutError(
                    str(exc),
                    commands=(*commands, *exc.commands),
                    statuses=(*statuses, *exc.statuses),
                    download_bytes=download + exc.download_bytes,
                ) from exc
            commands.append(argv)
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
        run((*prefix, "sparse-checkout", "set", "--no-cone", "--stdin"), ("\n".join(spec.patterns) + "\n").encode())
        run((*prefix, "checkout", "--quiet", "--detach", spec.commit_sha))
        checked_commands, checked_statuses, checked_download, disk, hashes = _validate_checkout(
            spec, partial, root=root, runner=runner, environment=environment
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
        try:
            _publish_no_replace(root_descriptor, partial, spec.name)
        except SparseCheckoutError as exc:
            raise SparseCheckoutError(str(exc), commands=commands, statuses=statuses, download_bytes=download) from exc
        partial_created = False
        os.fsync(root_descriptor)
        return CheckoutResult(spec.name, root / spec.name, spec.commit_sha, spec.patterns, tuple(commands), tuple(statuses), download, disk, hashes, False)
    except BaseException:
        if partial_created and partial_identity is not None and _path_matches_root(root, root_identity):
            try:
                current = os.stat(partial, dir_fd=root_descriptor, follow_symlinks=False)
            except OSError:
                current = None
            if current is not None and partial_identity == (current.st_dev, current.st_ino):
                try:
                    partial_descriptor, _ = open_directory_at(root_descriptor, partial)
                except ValueError:
                    partial_descriptor = -1
                if partial_descriptor >= 0:
                    try:
                        cleanup_exact_directory(
                            root_descriptor,
                            partial_descriptor,
                            FileIdentity(*partial_identity),
                            partial,
                        )
                    finally:
                        os.close(partial_descriptor)
        raise
    finally:
        os.close(root_descriptor)
