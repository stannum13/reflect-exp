"""Build the P2 source-metadata report from bounded local evidence only."""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Mapping, Sequence

import yaml

from reflect.sources import (
    LicenseStatus,
    MetadataStatus,
    PathStatus,
    SourceValidationError,
    load_lock,
    load_registry,
    validate_lock,
)


ROOT = Path(__file__).resolve().parents[1]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_TOP_KEYS = {"schema_version", "registry_sha256", "attempts"}
_ATTEMPT_REQUIRED = {
    "id",
    "command",
    "started_at_utc",
    "exit_code",
    "published_lock",
    "completed_entries",
}
_ATTEMPT_OPTIONAL = {
    "finished_at_utc",
    "summary",
    "incomplete_entry",
    "error",
    "rate_limit_reset_utc",
    "lock_absence_verified",
    "lock_sha256_before",
    "lock_sha256_after",
    "cache_validation",
}
_FAILURE_ONLY = {
    "incomplete_entry",
    "error",
    "rate_limit_reset_utc",
    "lock_absence_verified",
    "lock_sha256_before",
}


REQUIRED_COMMANDS: Mapping[str, tuple[str, ...]] = {
    "audit": (
        "env",
        "UV_CACHE_DIR=.cache/uv",
        "uv",
        "run",
        "python",
        "scripts/audit_references.py",
        "--require-complete",
    ),
    "full_tests": ("env", "UV_CACHE_DIR=.cache/uv", "uv", "run", "pytest", "-q"),
    "lock_check": ("env", "UV_CACHE_DIR=.cache/uv", "uv", "lock", "--check"),
    "safety": ("make", "safety-check"),
    "diff_check": ("git", "diff", "--check"),
    "boundary_paths": (
        "git",
        "ls-files",
        ".env",
        "*.pt",
        "*.pth",
        "*.ckpt",
        "*.safetensors",
        "results/**",
        "external/**",
        ".worktrees/**",
        ".superpowers/**",
    ),
    "boundary_large_files": (
        "find",
        ".",
        "-path",
        "./.git",
        "-prune",
        "-o",
        "-path",
        "./.venv",
        "-prune",
        "-o",
        "-path",
        "./.cache",
        "-prune",
        "-o",
        "-path",
        "./.superpowers",
        "-prune",
        "-o",
        "-type",
        "f",
        "-size",
        "+100M",
        "-print",
    ),
}


class _StringTimestampLoader(yaml.SafeLoader):
    """Safe YAML loader that does not silently coerce timestamps to datetime."""


_StringTimestampLoader.yaml_implicit_resolvers = copy.deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)
for _resolver_key, _resolvers in list(
    _StringTimestampLoader.yaml_implicit_resolvers.items()
):
    _StringTimestampLoader.yaml_implicit_resolvers[_resolver_key] = [
        resolver
        for resolver in _resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]


@dataclass(frozen=True)
class Attempt:
    id: str
    command: tuple[str, ...]
    started_at_utc: str
    finished_at_utc: str | None
    exit_code: int
    published_lock: bool
    completed_entries: tuple[str, ...]
    summary: str | None = None
    incomplete_entry: str | None = None
    error: str | None = None
    rate_limit_reset_utc: str | None = None
    lock_absence_verified: bool | None = None
    lock_sha256_before: str | None = None
    lock_sha256_after: str | None = None
    cache_validation: str | None = None


@dataclass(frozen=True)
class AttemptLog:
    schema_version: int
    registry_sha256: str
    attempts: tuple[Attempt, ...]
    source_text: str


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", tuple(self.command))
        if type(self.returncode) is not int:
            raise ValueError("command returncode must be an integer")
        if type(self.stdout) is not str or type(self.stderr) is not str:
            raise ValueError("command output must be text")


def _exact_keys(
    value: object,
    label: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError(f"{label} must be a mapping with string keys")
    keys = set(value)
    missing = required - keys
    extra = keys - required - optional
    if missing:
        raise ValueError(f"{label} has missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"{label} has extra keys: {sorted(extra)}")
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _canonical_utc(value: object, label: str) -> str:
    text = _text(value, label)
    if _UTC.fullmatch(text) is None:
        raise ValueError(f"{label} must use canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{label} must use canonical UTC YYYY-MM-DDTHH:MM:SSZ") from exc
    return text


def _optional_utc(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _canonical_utc(value, label)


def _sha256(value: object, label: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = _text(value, label)
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 string")
    return text


def parse_attempt_log(
    text: str,
    *,
    expected_registry_sha256: str,
    registry_names: Sequence[str],
) -> AttemptLog:
    """Parse and validate a P2 attempt log without filesystem or network access."""
    if type(text) is not str:
        raise ValueError("attempt log must be text")
    try:
        decoded = yaml.load(text, Loader=_StringTimestampLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"attempt log is malformed YAML: {exc}") from exc
    raw = _exact_keys(decoded, "attempt log", _TOP_KEYS)
    if raw["schema_version"] != 1 or type(raw["schema_version"]) is not int:
        raise ValueError("attempt log schema_version must be integer 1")
    registry_digest = _sha256(raw["registry_sha256"], "registry SHA-256")
    if registry_digest != expected_registry_sha256:
        raise ValueError("attempt log registry SHA-256 does not match registry")
    names = tuple(registry_names)
    if not names or len(set(names)) != len(names) or any(type(name) is not str for name in names):
        raise ValueError("registry names must be unique non-empty strings")
    name_set = set(names)
    attempts_raw = raw["attempts"]
    if not isinstance(attempts_raw, list) or not attempts_raw:
        raise ValueError("attempts must be a non-empty list")

    parsed: list[Attempt] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(attempts_raw):
        label = f"attempts[{index}]"
        attempt = _exact_keys(item, label, _ATTEMPT_REQUIRED, _ATTEMPT_OPTIONAL)
        attempt_id = _text(attempt["id"], f"{label}.id")
        if attempt_id in seen_ids:
            raise ValueError(f"{label}.id is duplicate")
        seen_ids.add(attempt_id)
        command_raw = attempt["command"]
        if not isinstance(command_raw, list) or not command_raw:
            raise ValueError(f"{label}.command must be a non-empty array")
        command = tuple(_text(part, f"{label}.command") for part in command_raw)
        completed_raw = attempt["completed_entries"]
        if not isinstance(completed_raw, list):
            raise ValueError(f"{label}.completed_entries must be an array")
        completed = tuple(
            _text(name, f"{label}.completed_entries") for name in completed_raw
        )
        if len(set(completed)) != len(completed):
            raise ValueError(f"{label}.completed_entries contains duplicate names")
        unknown = sorted(set(completed) - name_set)
        if unknown:
            raise ValueError(f"{label}.completed_entries contains unknown names: {unknown}")
        completed = tuple(sorted(completed))
        exit_code = attempt["exit_code"]
        if type(exit_code) is not int:
            raise ValueError(f"{label}.exit_code must be an integer")
        published = attempt["published_lock"]
        if type(published) is not bool:
            raise ValueError(f"{label}.published_lock must be a boolean")
        started = _canonical_utc(attempt["started_at_utc"], f"{label}.started_at_utc")
        finished = _optional_utc(attempt.get("finished_at_utc"), f"{label}.finished_at_utc")
        if finished is not None and finished < started:
            raise ValueError(f"{label}.finished_at_utc precedes started_at_utc")
        reset = _optional_utc(attempt.get("rate_limit_reset_utc"), f"{label}.rate_limit_reset_utc")
        before = _sha256(attempt.get("lock_sha256_before"), f"{label}.lock_sha256_before", optional=True)
        after = _sha256(attempt.get("lock_sha256_after"), f"{label}.lock_sha256_after", optional=True)
        absence = attempt.get("lock_absence_verified")
        if absence is not None and type(absence) is not bool:
            raise ValueError(f"{label}.lock_absence_verified must be a boolean")

        if exit_code != 0:
            if published:
                raise ValueError(f"{label} cannot publish a lock after failure")
            if finished is None or "error" not in attempt:
                raise ValueError(f"{label} failed attempt requires finish and error evidence")
            absence_proof = absence is True and before is None and after is None
            byte_proof = absence is None and before is not None and before == after
            if not (absence_proof or byte_proof):
                raise ValueError(f"{label} failed window lacks valid lock preservation proof")
        if published:
            if exit_code != 0 or finished is None:
                raise ValueError(f"{label} published lock requires successful finished command")
            if set(completed) != name_set or len(completed) != len(names):
                raise ValueError(f"{label} published lock does not cover the complete registry")
            if after is None:
                raise ValueError(f"{label} published lock requires lock_sha256_after")
            forbidden = sorted(_FAILURE_ONLY & set(attempt))
            if forbidden:
                raise ValueError(f"{label} published lock has failure-only keys: {forbidden}")

        parsed.append(
            Attempt(
                id=attempt_id,
                command=command,
                started_at_utc=started,
                finished_at_utc=finished,
                exit_code=exit_code,
                published_lock=published,
                completed_entries=completed,
                summary=_optional_text(attempt.get("summary"), f"{label}.summary"),
                incomplete_entry=_optional_text(attempt.get("incomplete_entry"), f"{label}.incomplete_entry"),
                error=_optional_text(attempt.get("error"), f"{label}.error"),
                rate_limit_reset_utc=reset,
                lock_absence_verified=absence,
                lock_sha256_before=before,
                lock_sha256_after=after,
                cache_validation=_optional_text(attempt.get("cache_validation"), f"{label}.cache_validation"),
            )
        )
    return AttemptLog(1, registry_digest, tuple(parsed), text)


def _validate_implementation_commit(project_root: Path, implementation_sha: str) -> str:
    if _GIT_SHA.fullmatch(implementation_sha) is None:
        raise ValueError("implementation SHA must be a 40- or 64-digit lowercase Git SHA")

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=project_root, capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise RuntimeError(f"evidence Git command failed: {' '.join(args)}\n{result.stderr}")
        return result.stdout.strip()

    resolved = git("rev-parse", "--verify", f"{implementation_sha}^{{commit}}")
    head = git("rev-parse", "HEAD")
    if resolved != head:
        raise RuntimeError(f"implementation SHA must equal current HEAD {head}, got {resolved}")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RuntimeError(f"evidence worktree must be clean:\n{status}")
    return resolved


def _validate_results(results: Mapping[str, CommandResult]) -> Mapping[str, CommandResult]:
    if set(results) != set(REQUIRED_COMMANDS):
        raise RuntimeError(
            f"verification results must have exact keys {sorted(REQUIRED_COMMANDS)}"
        )
    for name, command in REQUIRED_COMMANDS.items():
        result = results[name]
        if not isinstance(result, CommandResult):
            raise RuntimeError(f"{name} result has invalid type")
        if result.command != command:
            raise RuntimeError(f"{name} command does not match required command array")
        if result.returncode != 0:
            raise RuntimeError(f"{name} verification command failed with exit {result.returncode}")
    for name in ("diff_check", "boundary_paths", "boundary_large_files"):
        if results[name].stdout.strip() or results[name].stderr.strip():
            raise RuntimeError(f"{name} verification produced unexpected output")
    return results


def _command_block(result: CommandResult) -> str:
    command = " ".join(result.command)
    stdout = result.stdout.strip() or "(empty)"
    stderr = result.stderr.strip() or "(empty)"
    return f"$ {command}\nstdout:\n{stdout}\nstderr:\n{stderr}\nexit: {result.returncode}"


def build_report(
    *,
    project_root: Path,
    implementation_sha: str,
    command_results: Mapping[str, CommandResult],
    physical_deployment_allowed: bool,
    remote_enabled: bool,
    expected_registry_entries: int | None = None,
) -> str:
    """Construct a report from explicit local paths and injected command outcomes."""
    root = Path(project_root).resolve()
    if physical_deployment_allowed:
        raise RuntimeError("physical deployment must remain disabled")
    if remote_enabled:
        raise RuntimeError("remote execution must remain disabled")

    registry_path = root / "references" / "repos.yaml"
    lock_path = root / "references" / "repos.lock.yaml"
    attempts_path = root / "references" / "p2-live-attempts.yaml"
    try:
        registry = load_registry(registry_path)
        lock = load_lock(lock_path)
    except (SourceValidationError, OSError, ValueError) as exc:
        raise ValueError(f"complete P2 lock evidence is unavailable: {exc}") from exc
    lock_errors = validate_lock(registry, lock, require_complete=True)
    if lock_errors:
        raise ValueError(f"complete P2 lock validation failed: {'; '.join(lock_errors)}")
    if expected_registry_entries is not None and len(registry.repositories) != expected_registry_entries:
        raise ValueError(
            f"registry contains {len(registry.repositories)} entries, expected {expected_registry_entries}"
        )
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    try:
        attempts_text = attempts_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"attempt log is unavailable: {exc}") from exc
    attempt_log = parse_attempt_log(
        attempts_text,
        expected_registry_sha256=registry.registry_sha256,
        registry_names=tuple(entry.name for entry in registry.repositories),
    )
    publications = [attempt for attempt in attempt_log.attempts if attempt.published_lock]
    if len(publications) != 1 or publications[0] is not attempt_log.attempts[-1]:
        raise ValueError("attempt log must end with exactly one successful publication")
    if publications[0].lock_sha256_after != lock_digest:
        raise ValueError("published attempt lock digest does not match current lock bytes")

    resolved_sha = _validate_implementation_commit(root, implementation_sha)
    results = _validate_results(command_results)
    try:
        audit = json.loads(results["audit"].stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("audit verification did not emit valid JSON") from exc
    if not isinstance(audit, dict) or audit.get("ok") is not True or audit.get("errors") != []:
        raise RuntimeError("audit verification did not prove a complete clean audit")

    path_statuses = [status for entry in lock.entries for status in entry.path_statuses.values()]
    license_statuses = [entry.license_status for entry in lock.entries]
    expected_counts = {
        "registry_entries": len(registry.repositories),
        "lock_entries": len(lock.entries),
        "selected_paths": len(path_statuses),
        "discovered_licenses": license_statuses.count(LicenseStatus.DISCOVERED),
    }
    for field, expected in expected_counts.items():
        if audit.get(field) != expected:
            raise RuntimeError(f"audit {field} count does not match current lock evidence")
    try:
        safety = json.loads(results["safety"].stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("safety verification did not emit valid JSON") from exc
    if safety != {"simulation_only": True, "remote_enabled": False}:
        raise RuntimeError("safety verification did not prove local simulation-only state")

    timestamps = [
        _canonical_utc(entry.retrieved_at, f"lock entry {entry.name} retrieved_at")
        for entry in lock.entries
    ]
    exists = path_statuses.count(PathStatus.EXISTS)
    missing = path_statuses.count(PathStatus.MISSING)
    discovered = license_statuses.count(LicenseStatus.DISCOVERED)
    unknown = license_statuses.count(LicenseStatus.UNKNOWN)
    unavailable = license_statuses.count(LicenseStatus.UNAVAILABLE)
    metadata_resolved = sum(
        entry.metadata_status is MetadataStatus.RESOLVED for entry in lock.entries
    )
    evidence_blocks = "\n\n".join(
        _command_block(results[name])
        for name in (
            "audit",
            "full_tests",
            "lock_check",
            "safety",
            "diff_check",
            "boundary_paths",
            "boundary_large_files",
        )
    )
    attempt_history = attempt_log.source_text.rstrip()

    return f"""# P2 Run Report

## Executive result

The complete public-source metadata lock passed the offline P2 gate.

## Evidence base

- Implementation/evidence-base Git SHA: `{resolved_sha}`
- Registry SHA-256: `{registry.registry_sha256}`
- Complete lock SHA-256: `{lock_digest}`
- Retrieval interval: `{min(timestamps)}` through `{max(timestamps)}`
- Registry entries: `{len(registry.repositories)}`
- Lock entries: `{len(lock.entries)}`; metadata RESOLVED: `{metadata_resolved}`
- Selected paths: `{len(path_statuses)}` (`{exists}` EXISTS, `{missing}` MISSING)
- Licenses: `{discovered}` DISCOVERED, `{unknown}` UNKNOWN, `{unavailable}` UNAVAILABLE
- Physical deployment allowed: `false`; remote execution enabled: `false`

## Exact durable live-attempt history

```yaml
{attempt_history}
```

The final successful attempt covers all `{len(registry.repositories)}` unique registry
entries and binds its `lock_sha256_after` to the current lock bytes. Every failed
window records either verified lock absence or identical before/after lock digests.

## Offline verification evidence

```text
{evidence_blocks}
```

## Repository boundary

- Forbidden tracked-path scan: exit 0, empty output.
- Unapproved files larger than 100 MiB: exit 0, empty output.
- `git diff --check`: exit 0, empty output.
- No network or live resolver command was run by this report generator.

## Scope and limitations

- GitHub license metadata is an observed upstream signal, not a legal conclusion.
- `MISSING` selected paths are retained as explicit compatibility evidence, not guessed.
- No physical deployment, remote execution, model download, checkout, or experiment ran.

## Highest-value next bounded action

Run the P3 source compatibility audit against this immutable lock before adapting
any upstream source or beginning empirical experiments.
"""


def _safe_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "PHYSICAL_DEPLOYMENT_ALLOWED": "false",
            "REFLECT_REMOTE_ENABLED": "0",
            "UV_CACHE_DIR": ".cache/uv",
        }
    )
    return environment


def _run(command: tuple[str, ...], *, root: Path) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=root,
        env=_safe_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)


def _environment_enabled(name: str) -> bool:
    value = os.environ.get(name, "").strip().casefold()
    if value in {"", "0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on"}:
        return True
    raise RuntimeError(f"{name} has an unrecognized safety value")


def main(argv: Sequence[str] | None = None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-base-sha", required=True)
    arguments = parser.parse_args(argv)
    project_root = Path(root) if root is not None else ROOT

    # Validate all immutable inputs before running even bounded local verification.
    registry = load_registry(project_root / "references" / "repos.yaml")
    lock = load_lock(project_root / "references" / "repos.lock.yaml")
    errors = validate_lock(registry, lock, require_complete=True)
    if len(registry.repositories) != 45 or errors:
        raise RuntimeError(f"production P2 lock is incomplete: {'; '.join(errors)}")
    attempts = parse_attempt_log(
        (project_root / "references" / "p2-live-attempts.yaml").read_text(encoding="utf-8"),
        expected_registry_sha256=registry.registry_sha256,
        registry_names=tuple(entry.name for entry in registry.repositories),
    )
    lock_digest = hashlib.sha256(
        (project_root / "references" / "repos.lock.yaml").read_bytes()
    ).hexdigest()
    if not attempts.attempts[-1].published_lock or attempts.attempts[-1].lock_sha256_after != lock_digest:
        raise RuntimeError("production attempt log does not bind the current complete lock")
    _validate_implementation_commit(project_root, arguments.evidence_base_sha)

    results = {
        name: _run(command, root=project_root)
        for name, command in REQUIRED_COMMANDS.items()
    }
    report = build_report(
        project_root=project_root,
        implementation_sha=arguments.evidence_base_sha,
        command_results=results,
        physical_deployment_allowed=_environment_enabled("PHYSICAL_DEPLOYMENT_ALLOWED"),
        remote_enabled=_environment_enabled("REFLECT_REMOTE_ENABLED"),
        expected_registry_entries=45,
    )
    target = project_root / "RUN_REPORT.md"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=project_root, prefix=".RUN_REPORT.md.", delete=False
    ) as temporary:
        temporary.write(report)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
