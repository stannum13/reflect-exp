"""Offline audit for locked source metadata and repository boundaries."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

from reflect.sources import (
    LicenseStatus,
    ReuseMode,
    SourceLock,
    SourceRegistry,
    SourceValidationError,
    load_lock,
    load_registry,
    validate_lock,
)


ROOT = Path(__file__).resolve().parents[1]
_GIT_TIMEOUT_SECONDS = 10.0
_CHECKOUT_ROOTS = frozenset({"external", "vendor", "third_party"})
_MODEL_SUFFIXES = frozenset({".ckpt", ".pt", ".pth", ".safetensors", ".onnx"})
_MODEL_FILENAMES = frozenset(
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
_MAX_SOURCE_BYTES = 1024 * 1024
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SPDX_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*\Z")
_MARKER = re.compile(
    r"(?:^|\s)(Upstream-Source|Upstream-Revision|SPDX-License-Identifier):\s*(.*?)\s*\Z"
)


@dataclass(frozen=True)
class AuditResult:
    registry_entries: int
    lock_entries: int
    selected_paths: int
    discovered_licenses: int
    tracked_files: int
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        """Return the stable public command summary."""
        return {
            "registry_entries": self.registry_entries,
            "lock_entries": self.lock_entries,
            "selected_paths": self.selected_paths,
            "discovered_licenses": self.discovered_licenses,
            "tracked_files": self.tracked_files,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.pop("SSH_ASKPASS", None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LITERAL_PATHSPECS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return environment


def _tracked_files(root: Path) -> tuple[tuple[str, ...], str | None]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--"],
            cwd=root,
            env=_git_environment(),
            capture_output=True,
            text=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (), f"git ls-files failed: {type(exc).__name__}"
    if completed.returncode != 0:
        return (), f"git ls-files failed with return code {completed.returncode}"
    output = completed.stdout
    if type(output) is not bytes or (output and not output.endswith(b"\0")):
        return (), "git ls-files returned malformed output"
    raw_paths = output[:-1].split(b"\0") if output else []
    if any(not item for item in raw_paths):
        return (), "git ls-files returned malformed output"
    try:
        paths = tuple(item.decode("utf-8", errors="strict") for item in raw_paths)
    except UnicodeDecodeError:
        return (), "git ls-files returned malformed UTF-8 output"
    if len(set(paths)) != len(paths):
        return (), "git ls-files returned duplicate paths"
    for path in paths:
        pure = PurePosixPath(path)
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            return (), "git ls-files returned malformed path output"
    return tuple(sorted(paths)), None


def _path_errors(paths: Sequence[str]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        parts = PurePosixPath(path).parts
        folded = tuple(part.casefold() for part in parts)
        if folded and folded[0] in _CHECKOUT_ROOTS:
            errors.append(f"tracked source checkout path: {path}")
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix in _MODEL_SUFFIXES or folded[-1] in _MODEL_FILENAMES:
            errors.append(f"tracked model/checkpoint artifact: {path}")
    return errors


def _line_marker(line: str) -> tuple[str, str] | None:
    match = _MARKER.search(line)
    if match is None:
        return None
    value = match.group(2).strip()
    for ending in ("*/", "-->"):
        if value.endswith(ending):
            value = value[: -len(ending)].rstrip()
    return match.group(1), value


def _marker_occurrences(lines: Sequence[str], marker: str) -> list[tuple[int, str]]:
    occurrences: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        parsed = _line_marker(line)
        if parsed is not None and parsed[0] == marker:
            occurrences.append((index, parsed[1]))
    return occurrences


def _inspect_reflect_sources(
    root: Path, paths: Sequence[str]
) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    sources: dict[str, tuple[str, ...]] = {}
    errors: list[str] = []
    for relative in paths:
        parts = PurePosixPath(relative).parts
        if not parts or parts[0] != "reflect":
            continue
        path = root / relative
        try:
            metadata = path.lstat()
        except OSError as exc:
            errors.append(
                f"cannot safely inspect tracked source {relative}: {type(exc).__name__}"
            )
            continue
        if not stat.S_ISREG(metadata.st_mode):
            errors.append(f"tracked source is not a regular file: {relative}")
            continue
        if metadata.st_size > _MAX_SOURCE_BYTES:
            errors.append(f"tracked source exceeds inspection limit: {relative}")
            continue
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or (
                    opened.st_dev,
                    opened.st_ino,
                ) != (metadata.st_dev, metadata.st_ino):
                    errors.append(
                        f"tracked source changed during inspection: {relative}"
                    )
                    continue
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    content = stream.read(_MAX_SOURCE_BYTES + 1)
            finally:
                os.close(descriptor)
        except OSError as exc:
            errors.append(
                f"cannot safely inspect tracked source {relative}: {type(exc).__name__}"
            )
            continue
        if len(content) > _MAX_SOURCE_BYTES:
            errors.append(f"tracked source exceeds inspection limit: {relative}")
            continue
        try:
            sources[relative] = tuple(
                content.decode("utf-8", errors="strict").splitlines()
            )
        except UnicodeDecodeError:
            errors.append(f"tracked source is not valid UTF-8: {relative}")
    return sources, errors


def _attribution_errors(
    sources: dict[str, tuple[str, ...]],
    registry: SourceRegistry | None,
    lock: SourceLock | None,
) -> list[str]:
    if registry is None or lock is None:
        return []
    registry_by_source = {
        identity: entry.name
        for entry in registry.repositories
        for identity in (entry.name, entry.url)
    }
    lock_by_name = {entry.name: entry for entry in lock.entries}
    errors: list[str] = []
    for relative, lines in sources.items():
        source_markers = _marker_occurrences(lines, "Upstream-Source")
        if not source_markers:
            continue
        if len(source_markers) != 1:
            errors.append(
                f"source must have exactly one Upstream-Source marker: {relative}"
            )
            continue
        index, source = source_markers[0]
        revision_markers = _marker_occurrences(lines, "Upstream-Revision")
        license_markers = _marker_occurrences(lines, "SPDX-License-Identifier")
        if len(revision_markers) != 1:
            errors.append(
                f"source must have exactly one Upstream-Revision marker: {relative}"
            )
        if len(license_markers) != 1:
            errors.append(
                f"source must have exactly one SPDX-License-Identifier marker: {relative}"
            )
        revision = revision_markers[0][1] if len(revision_markers) == 1 else ""
        license_identifier = license_markers[0][1] if len(license_markers) == 1 else ""
        if (
            len(revision_markers) != 1
            or revision_markers[0][0] != index + 1
            or _SHA40.fullmatch(revision) is None
        ):
            errors.append(f"invalid or missing adjacent Upstream-Revision: {relative}")
        if (
            len(license_markers) != 1
            or license_markers[0][0] != index + 2
            or _SPDX_IDENTIFIER.fullmatch(license_identifier) is None
        ):
            errors.append(
                f"invalid or missing adjacent SPDX-License-Identifier: {relative}"
            )
        name = registry_by_source.get(source)
        if name is None or name not in lock_by_name:
            errors.append(f"unknown Upstream-Source in {relative}: {source}")
            continue
        locked = lock_by_name[name]
        if revision and locked.commit_sha != revision:
            errors.append(f"Upstream-Revision does not match lock: {relative}")
        if locked.license_status is not LicenseStatus.DISCOVERED:
            errors.append(f"locked attribution license is not discovered: {relative}")
        elif (
            locked.license_spdx is None
            or _SPDX_IDENTIFIER.fullmatch(locked.license_spdx) is None
        ):
            errors.append(f"invalid locked attribution SPDX: {relative}")
        elif (
            _SPDX_IDENTIFIER.fullmatch(license_identifier) is not None
            and license_identifier != locked.license_spdx
        ):
            errors.append(f"attribution SPDX does not match lock: {relative}")
    return errors


def audit_repository(root: Path, *, require_complete: bool) -> AuditResult:
    """Audit registry, lock, tracked paths, and explicit source attribution offline."""
    project_root = Path(root).resolve()
    errors: list[str] = []
    registry: SourceRegistry | None = None
    lock: SourceLock | None = None
    try:
        registry = load_registry(project_root / "references" / "repos.yaml")
    except (SourceValidationError, OSError, ValueError) as exc:
        errors.append(f"registry validation failed: {exc}")
    try:
        lock = load_lock(project_root / "references" / "repos.lock.yaml")
    except (SourceValidationError, OSError, ValueError) as exc:
        errors.append(f"lock validation failed: {exc}")
    if registry is not None and lock is not None:
        errors.extend(validate_lock(registry, lock, require_complete=require_complete))
        if require_complete:
            locked_by_name = {entry.name: entry for entry in lock.entries}
            for entry in registry.repositories:
                locked = locked_by_name.get(entry.name)
                if (
                    locked is not None
                    and entry.mode
                    in {ReuseMode.DIRECT_DEPENDENCY, ReuseMode.ADAPTER_DEPENDENCY}
                    and locked.license_evidence_url is None
                ):
                    errors.append(f"missing license observation: {entry.name}")

    paths, inventory_error = _tracked_files(project_root)
    if inventory_error is not None:
        errors.append(inventory_error)
    else:
        errors.extend(_path_errors(paths))
        sources, source_errors = _inspect_reflect_sources(project_root, paths)
        errors.extend(source_errors)
        errors.extend(_attribution_errors(sources, registry, lock))

    return AuditResult(
        registry_entries=len(registry.repositories) if registry is not None else 0,
        lock_entries=len(lock.entries) if lock is not None else 0,
        selected_paths=(
            sum(len(entry.selected_paths) for entry in registry.repositories)
            if registry is not None
            else 0
        ),
        discovered_licenses=(
            sum(
                entry.license_status is LicenseStatus.DISCOVERED
                for entry in lock.entries
            )
            if lock is not None
            else 0
        ),
        tracked_files=len(paths),
        errors=tuple(sorted(set(errors))),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit locked source metadata without network access."
    )
    parser.add_argument("--require-complete", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, *, root: Path | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = audit_repository(
        Path(root) if root is not None else ROOT,
        require_complete=arguments.require_complete,
    )
    print(json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
