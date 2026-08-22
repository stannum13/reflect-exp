"""Fail-closed local I/O primitives for the P2 report generator."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import subprocess
from typing import Mapping, Sequence


_MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
HARDENED_GIT_PREFIX = (
    "git",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
)
SAFE_GIT_ENV: Mapping[str, str] = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_LITERAL_PATHSPECS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
}
_CHECKOUT_COMPONENTS = frozenset(
    {
        ".superpowers",
        ".worktrees",
        "external",
        "results",
        "third_party",
        "thirdparty",
        "vendor",
    }
)
_MODEL_SUFFIXES = frozenset({".ckpt", ".pt", ".pth", ".safetensors", ".onnx"})
_MODEL_NAMES = frozenset(
    {
        "adapter_model.bin",
        "checkpoint",
        "checkpoint.bin",
        "diffusion_pytorch_model.bin",
        "model",
        "model.bin",
        "pytorch_model.bin",
        "weights",
        "weights.bin",
    }
)
_SECRET_NAMES = frozenset(
    {
        "credentials",
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "secret",
        "secrets",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "service-account.json",
        "service_account.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "private-key.pem",
        "private_key.pem",
        ".netrc",
        ".npmrc",
        ".pypirc",
    }
)


@dataclass(frozen=True)
class EvidenceSnapshot:
    registry: bytes
    lock: bytes
    attempts: bytes


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_directory_path_no_follow(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    descriptor = os.open(os.sep, _directory_flags())
    try:
        for component in absolute.parts[1:]:
            if component in {"", ".", ".."}:
                raise ValueError("directory path contains an unsafe component")
            try:
                child = os.open(component, _directory_flags(), dir_fd=descriptor)
            except OSError as exc:
                raise ValueError(
                    f"directory path failed component no-follow open: {component}: {exc}"
                ) from exc
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_file_at(directory_fd: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise ValueError(f"evidence file {name} failed no-follow open: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"evidence file {name} is not regular")
        if before.st_size > _MAX_EVIDENCE_BYTES:
            raise ValueError(f"evidence file {name} exceeds bounded snapshot size")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, _MAX_EVIDENCE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_EVIDENCE_BYTES:
                raise ValueError(f"evidence file {name} exceeds bounded snapshot size")
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
        )
        content = b"".join(chunks)
        if identity_before != identity_after or len(content) != before.st_size:
            raise ValueError(f"evidence file {name} changed during stable snapshot")
        return content
    finally:
        os.close(descriptor)


def read_evidence_snapshot(root: Path) -> EvidenceSnapshot:
    project_root = Path(root)
    root_fd = _open_directory_path_no_follow(project_root)
    try:
        try:
            references_fd = os.open("references", _directory_flags(), dir_fd=root_fd)
        except OSError as exc:
            raise ValueError(f"references directory failed no-follow open: {exc}") from exc
        try:
            return EvidenceSnapshot(
                registry=_read_file_at(references_fd, "repos.yaml"),
                lock=_read_file_at(references_fd, "repos.lock.yaml"),
                attempts=_read_file_at(references_fd, "p2-live-attempts.yaml"),
            )
        finally:
            os.close(references_fd)
    finally:
        os.close(root_fd)


def hardened_environment(
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.pop("SSH_ASKPASS", None)
    environment.update(SAFE_GIT_ENV)
    if extra:
        environment.update(extra)
    return environment


def run_git(
    root: Path, arguments: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    command = [*HARDENED_GIT_PREFIX, *arguments]
    return subprocess.run(
        command,
        cwd=Path(root),
        env=hardened_environment(),
        capture_output=True,
        text=True,
        check=False,
    )


def validate_implementation_commit(root: Path, implementation_sha: str) -> str:
    if re_full_git_sha(implementation_sha) is False:
        raise ValueError("implementation SHA must be a lowercase Git SHA")

    def checked(*arguments: str) -> str:
        completed = run_git(root, arguments)
        if completed.returncode:
            raise RuntimeError(
                f"evidence Git command failed: {' '.join(arguments)}\n{completed.stderr}"
            )
        return completed.stdout.strip()

    resolved = checked("rev-parse", "--verify", f"{implementation_sha}^{{commit}}")
    head = checked("rev-parse", "HEAD")
    if resolved != head:
        raise RuntimeError(f"implementation SHA must equal current HEAD {head}, got {resolved}")
    status = checked("status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RuntimeError(f"evidence worktree must be clean:\n{status}")
    return resolved


def re_full_git_sha(value: object) -> bool:
    if type(value) is not str or len(value) not in {40, 64}:
        return False
    return all(character in "0123456789abcdef" for character in value)


def forbidden_tracked_paths(paths: Sequence[str]) -> tuple[str, ...]:
    forbidden: list[str] = []
    for path in paths:
        if type(path) is not str or not path or path.startswith("/") or "\\" in path:
            forbidden.append(str(path))
            continue
        parts = PurePosixPath(path).parts
        folded = tuple(part.casefold() for part in parts)
        if any(part in {"", ".", ".."} for part in parts):
            forbidden.append(path)
            continue
        filename = folded[-1]
        environment_secret = filename != ".env.example" and (
            filename == ".env" or filename.startswith(".env.")
        )
        secret_prefix = filename.startswith(
            (
                "credential.",
                "credentials.",
                "secret.",
                "secrets.",
                "service-account",
                "service_account",
            )
        )
        private_key = filename.startswith(("id_", "private-key", "private_key")) or filename.endswith(
            (".pem", ".key", ".p12", ".pfx")
        )
        if (
            any(part in _CHECKOUT_COMPONENTS for part in folded)
            or environment_secret
            or filename in _SECRET_NAMES
            or secret_prefix
            or private_key
            or PurePosixPath(filename).suffix in _MODEL_SUFFIXES
            or filename in _MODEL_NAMES
        ):
            forbidden.append(path)
    return tuple(sorted(set(forbidden)))


def run_local_command(
    root: Path, command: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        tuple(command),
        cwd=Path(root),
        env=hardened_environment(
            {
                "PHYSICAL_DEPLOYMENT_ALLOWED": "false",
                "REFLECT_REMOTE_ENABLED": "0",
                "UV_CACHE_DIR": ".cache/uv",
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )


def atomic_write_report(root: Path, content: str) -> None:
    if type(content) is not str:
        raise ValueError("report content must be text")
    root_fd = _open_directory_path_no_follow(Path(root))
    temporary_name = f".RUN_REPORT.md.{secrets.token_hex(12)}"
    descriptor: int | None = None
    replaced = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=root_fd,
        )
        os.fchmod(descriptor, 0o600)
        payload = content.encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short report write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary_name,
            "RUN_REPORT.md",
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
        )
        replaced = True
        os.fsync(root_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not replaced:
            try:
                os.unlink(temporary_name, dir_fd=root_fd)
            except FileNotFoundError:
                pass
        os.close(root_fd)
