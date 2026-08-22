"""Offline audit for locked source metadata and repository boundaries."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
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
_MODEL_DIRECTORIES = frozenset(
    {"checkpoint", "checkpoints", "models", "model_weights", "weights"}
)
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
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
        if suffix in _MODEL_SUFFIXES:
            errors.append(f"tracked model/checkpoint artifact: {path}")
        elif any(part in _MODEL_DIRECTORIES for part in folded[:-1]):
            errors.append(f"tracked model/checkpoint directory: {path}")
    return errors


def _marker_value(line: str, marker: str) -> str | None:
    match = _MARKER.search(line)
    if match is None or match.group(1) != marker:
        return None
    value = match.group(2).strip()
    for ending in ("*/", "-->"):
        if value.endswith(ending):
            value = value[: -len(ending)].rstrip()
    return value or None


def _attribution_errors(
    root: Path,
    paths: Sequence[str],
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
    for relative in paths:
        parts = PurePosixPath(relative).parts
        if not parts or parts[0] != "reflect":
            continue
        path = root / relative
        try:
            if path.is_symlink() or not path.is_file():
                continue
            content = path.read_bytes()
        except OSError as exc:
            errors.append(
                f"could not inspect tracked source {relative}: {type(exc).__name__}"
            )
            continue
        if b"Upstream-Source:" not in content:
            continue
        try:
            lines = content.decode("utf-8", errors="strict").splitlines()
        except UnicodeDecodeError:
            errors.append(f"invalid UTF-8 attribution marker: {relative}")
            continue
        source_indexes = [
            index
            for index, line in enumerate(lines)
            if _marker_value(line, "Upstream-Source") is not None
        ]
        if len(source_indexes) != 1:
            errors.append(
                f"source must have exactly one Upstream-Source marker: {relative}"
            )
            continue
        index = source_indexes[0]
        source = _marker_value(lines[index], "Upstream-Source")
        revision = (
            _marker_value(lines[index + 1], "Upstream-Revision")
            if index + 1 < len(lines)
            else None
        )
        license_identifier = (
            _marker_value(lines[index + 2], "SPDX-License-Identifier")
            if index + 2 < len(lines)
            else None
        )
        if revision is None or _SHA40.fullmatch(revision) is None:
            errors.append(f"invalid or missing adjacent Upstream-Revision: {relative}")
        if license_identifier is None:
            errors.append(
                f"invalid or missing adjacent SPDX-License-Identifier: {relative}"
            )
        name = registry_by_source.get(source or "")
        if name is None or name not in lock_by_name:
            errors.append(f"unknown Upstream-Source in {relative}: {source or ''}")
        elif revision is not None and lock_by_name[name].commit_sha != revision:
            errors.append(f"Upstream-Revision does not match lock: {relative}")
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
        errors.extend(_attribution_errors(project_root, paths, registry, lock))

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
