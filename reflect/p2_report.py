"""Pure P2 attempt-evidence validation and report rendering."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import html
import json
import re
from typing import Any, Mapping, Sequence

import yaml

from reflect._p2_report_io import HARDENED_GIT_PREFIX, forbidden_tracked_paths
from reflect.sources import (
    LicenseStatus,
    LockedEntry,
    MetadataStatus,
    PathStatus,
    RegistryEntry,
    SourceLock,
    SourceRegistry,
    validate_lock,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
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
_REGISTRY_KEYS = {
    "verified_at",
    "large_model_downloads_default",
    "physical_deployment_default",
    "repositories",
}
_REGISTRY_ENTRY_REQUIRED = {
    "name",
    "url",
    "mode",
    "experiments",
    "selected_paths",
    "use",
}
_LOCK_KEYS = {"registry_sha256", "generated_at", "entries"}
_LOCK_ENTRY_KEYS = {
    "name",
    "url",
    "default_branch",
    "commit_sha",
    "retrieved_at",
    "metadata_evidence",
    "license_spdx",
    "license_status",
    "license_evidence_url",
    "path_statuses",
    "path_evidence_urls",
    "metadata_status",
}
_AUDIT_KEYS = {
    "registry_entries",
    "lock_entries",
    "selected_paths",
    "discovered_licenses",
    "tracked_files",
    "errors",
    "ok",
}
_FETCH_PREFIX = (
    "env",
    "UV_CACHE_DIR=.cache/uv",
    "uv",
    "run",
    "python",
    "scripts/fetch_reference.py",
)
_FETCH_ALL = (*_FETCH_PREFIX, "--all-metadata-only")


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
    "diff_check": (*HARDENED_GIT_PREFIX, "diff", "--check"),
    "boundary_paths": (*HARDENED_GIT_PREFIX, "ls-files", "-z", "--"),
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


class StrictYamlLoader(yaml.SafeLoader):
    """Safe loader with strings for timestamps and duplicate-key rejection."""


StrictYamlLoader.yaml_implicit_resolvers = copy.deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)
for _key, _resolvers in list(StrictYamlLoader.yaml_implicit_resolvers.items()):
    StrictYamlLoader.yaml_implicit_resolvers[_key] = [
        resolver
        for resolver in _resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]


def _construct_unique_mapping(
    loader: StrictYamlLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "mapping key is not hashable",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


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


@dataclass(frozen=True)
class ValidatedEvidence:
    registry: SourceRegistry
    lock: SourceLock
    attempts: AttemptLog
    lock_digest: str
    retrieval_timestamps: tuple[str, ...]


def _yaml(text: str, label: str) -> object:
    try:
        return yaml.load(text, Loader=StrictYamlLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"{label} is malformed YAML: {exc}") from exc


def _exact_keys(
    value: object,
    label: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> Mapping[str, Any]:
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
    return None if value is None else _text(value, label)


def canonical_utc(value: object, label: str) -> str:
    text = _text(value, label)
    if _UTC.fullmatch(text) is None:
        raise ValueError(f"{label} must use canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{label} must use canonical UTC YYYY-MM-DDTHH:MM:SSZ") from exc
    return text


def _optional_utc(value: object, label: str) -> str | None:
    return None if value is None else canonical_utc(value, label)


def _sha256(value: object, label: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = _text(value, label)
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 string")
    return text


def _allowlisted_fetch_command(
    command: tuple[str, ...], registry_names: set[str]
) -> bool:
    if command == _FETCH_ALL:
        return True
    return (
        len(command) == len(_FETCH_PREFIX) + 3
        and command[: len(_FETCH_PREFIX)] == _FETCH_PREFIX
        and command[len(_FETCH_PREFIX)] == "--name"
        and command[len(_FETCH_PREFIX) + 1] in registry_names
        and command[-1] == "--metadata-only"
    )


def parse_attempt_log(
    text: str,
    *,
    expected_registry_sha256: str,
    registry_names: Sequence[str],
) -> AttemptLog:
    """Parse strict durable attempt evidence without filesystem access."""
    if type(text) is not str:
        raise ValueError("attempt log must be text")
    raw = _exact_keys(_yaml(text, "attempt log"), "attempt log", _TOP_KEYS)
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("attempt log schema_version must be integer 1")
    digest = _sha256(raw["registry_sha256"], "registry SHA-256")
    if digest != expected_registry_sha256:
        raise ValueError("attempt log registry SHA-256 does not match registry")
    names = tuple(registry_names)
    if (
        not names
        or any(type(name) is not str or not name for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("registry names must be unique non-empty strings")
    name_set = set(names)
    raw_attempts = raw["attempts"]
    if not isinstance(raw_attempts, list) or not raw_attempts:
        raise ValueError("attempts must be a non-empty list")

    parsed: list[Attempt] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_attempts):
        label = f"attempts[{index}]"
        item = _exact_keys(item, label, _ATTEMPT_REQUIRED, _ATTEMPT_OPTIONAL)
        attempt_id = _text(item["id"], f"{label}.id")
        if attempt_id in seen_ids:
            raise ValueError(f"{label}.id is duplicate")
        seen_ids.add(attempt_id)
        raw_command = item["command"]
        if not isinstance(raw_command, list) or not raw_command:
            raise ValueError(f"{label}.command must be a non-empty array")
        command = tuple(_text(part, f"{label}.command") for part in raw_command)
        if not _allowlisted_fetch_command(command, name_set):
            raise ValueError(f"{label}.command is not an allowlisted resolver command")
        raw_completed = item["completed_entries"]
        if not isinstance(raw_completed, list):
            raise ValueError(f"{label}.completed_entries must be an array")
        completed = tuple(
            _text(name, f"{label}.completed_entries") for name in raw_completed
        )
        if len(set(completed)) != len(completed):
            raise ValueError(f"{label}.completed_entries contains duplicate names")
        unknown = sorted(set(completed) - name_set)
        if unknown:
            raise ValueError(f"{label}.completed_entries contains unknown names: {unknown}")
        completed = tuple(sorted(completed))
        exit_code = item["exit_code"]
        published = item["published_lock"]
        if type(exit_code) is not int:
            raise ValueError(f"{label}.exit_code must be an integer")
        if type(published) is not bool:
            raise ValueError(f"{label}.published_lock must be a boolean")
        started = canonical_utc(item["started_at_utc"], f"{label}.started_at_utc")
        finished = _optional_utc(item.get("finished_at_utc"), f"{label}.finished_at_utc")
        reset = _optional_utc(
            item.get("rate_limit_reset_utc"), f"{label}.rate_limit_reset_utc"
        )
        if finished is not None and finished < started:
            raise ValueError(f"{label}.finished_at_utc precedes started_at_utc")
        if reset is not None and (finished is None or reset <= finished):
            raise ValueError(f"{label}.rate-limit reset must be after finish")
        if parsed:
            prior = parsed[-1]
            lower_bound = prior.finished_at_utc or prior.started_at_utc
            if started < lower_bound:
                raise ValueError(f"{label} violates global chronology")
        before = _sha256(
            item.get("lock_sha256_before"), f"{label}.lock_sha256_before", optional=True
        )
        after = _sha256(
            item.get("lock_sha256_after"), f"{label}.lock_sha256_after", optional=True
        )
        absence = item.get("lock_absence_verified")
        if absence is not None and type(absence) is not bool:
            raise ValueError(f"{label}.lock_absence_verified must be a boolean")
        if exit_code != 0:
            if published:
                raise ValueError(f"{label} cannot publish a lock after failure")
            if finished is None or "error" not in item:
                raise ValueError(f"{label} failed attempt requires finish and error evidence")
            absence_proof = absence is True and before is None and after is None
            byte_proof = absence is None and before is not None and before == after
            if not (absence_proof or byte_proof):
                raise ValueError(f"{label} failed window lacks valid lock preservation proof")
        if published:
            if command != _FETCH_ALL:
                raise ValueError(f"{label} final publication must use all-metadata command")
            if exit_code != 0 or finished is None:
                raise ValueError(f"{label} published lock requires successful finished command")
            if set(completed) != name_set or len(completed) != len(names):
                raise ValueError(f"{label} published lock does not cover complete registry")
            if after is None:
                raise ValueError(f"{label} published lock requires lock_sha256_after")
            forbidden = sorted(_FAILURE_ONLY & set(item))
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
                summary=_optional_text(item.get("summary"), f"{label}.summary"),
                incomplete_entry=_optional_text(
                    item.get("incomplete_entry"), f"{label}.incomplete_entry"
                ),
                error=_optional_text(item.get("error"), f"{label}.error"),
                rate_limit_reset_utc=reset,
                lock_absence_verified=absence,
                lock_sha256_before=before,
                lock_sha256_after=after,
                cache_validation=_optional_text(
                    item.get("cache_validation"), f"{label}.cache_validation"
                ),
            )
        )
    publications = [attempt for attempt in parsed if attempt.published_lock]
    if publications and (len(publications) != 1 or publications[0] is not parsed[-1]):
        raise ValueError("attempt log permits exactly one final publication as last attempt")
    return AttemptLog(1, digest, tuple(parsed), text)


def _load_registry(data: bytes) -> SourceRegistry:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("registry is not UTF-8") from exc
    raw = _exact_keys(_yaml(text, "registry"), "registry", _REGISTRY_KEYS)
    repositories = raw["repositories"]
    if not isinstance(repositories, list):
        raise ValueError("repositories must be a list")
    entries: list[RegistryEntry] = []
    for index, value in enumerate(repositories):
        entry = _exact_keys(
            value,
            f"repositories[{index}]",
            _REGISTRY_ENTRY_REQUIRED,
            {"caveat", "justification"},
        )
        entries.append(
            RegistryEntry(
                name=entry["name"],
                url=entry["url"],
                mode=entry["mode"],
                experiments=entry["experiments"],
                selected_paths=entry["selected_paths"],
                use=entry["use"],
                caveat=entry.get("caveat"),
                justification=entry.get("justification"),
            )
        )
    return SourceRegistry(
        verified_at=raw["verified_at"],
        large_model_downloads_default=raw["large_model_downloads_default"],
        physical_deployment_default=raw["physical_deployment_default"],
        repositories=tuple(entries),
        registry_sha256=hashlib.sha256(data).hexdigest(),
    )


def _load_lock(data: bytes) -> SourceLock:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("lock is not UTF-8") from exc
    raw = _exact_keys(_yaml(text, "lock"), "lock", _LOCK_KEYS)
    entries = raw["entries"]
    if not isinstance(entries, list):
        raise ValueError("lock entries must be a list")
    parsed = [
        LockedEntry(
            **_exact_keys(value, f"entries[{index}]", _LOCK_ENTRY_KEYS)
        )
        for index, value in enumerate(entries)
    ]
    return SourceLock(
        registry_sha256=raw["registry_sha256"],
        generated_at=raw["generated_at"],
        entries=tuple(parsed),
    )


def require_safe_state(
    *, physical_deployment_allowed: bool, remote_enabled: bool
) -> None:
    if type(physical_deployment_allowed) is not bool or type(remote_enabled) is not bool:
        raise RuntimeError("physical and remote safety values must be booleans")
    if physical_deployment_allowed:
        raise RuntimeError("physical deployment must remain disabled")
    if remote_enabled:
        raise RuntimeError("remote execution must remain disabled")


def _parse_tracked_paths(output: str) -> tuple[str, ...]:
    if not output:
        return ()
    if not output.endswith("\0"):
        raise RuntimeError("boundary_paths returned malformed non-NUL inventory")
    paths = tuple(output[:-1].split("\0"))
    if any(not path for path in paths) or len(set(paths)) != len(paths):
        raise RuntimeError("boundary_paths returned malformed path inventory")
    return paths


def _validate_audit(
    output: str,
    *,
    registry_entries: int,
    lock_entries: int,
    selected_paths: int,
    discovered_licenses: int,
    tracked_files: int,
) -> None:
    try:
        audit = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("audit verification did not emit valid JSON") from exc
    if not isinstance(audit, dict) or set(audit) != _AUDIT_KEYS:
        raise RuntimeError("audit JSON must have exact keys")
    for field in (
        "registry_entries",
        "lock_entries",
        "selected_paths",
        "discovered_licenses",
        "tracked_files",
    ):
        if type(audit[field]) is not int:
            raise RuntimeError(f"audit {field} must be an integer")
    if type(audit["ok"]) is not bool:
        raise RuntimeError("audit ok must be a boolean")
    if not isinstance(audit["errors"], list) or any(
        type(error) is not str for error in audit["errors"]
    ):
        raise RuntimeError("audit errors must be a list of strings")
    expected = {
        "registry_entries": registry_entries,
        "lock_entries": lock_entries,
        "selected_paths": selected_paths,
        "discovered_licenses": discovered_licenses,
        "tracked_files": tracked_files,
    }
    if any(audit[field] != value for field, value in expected.items()):
        raise RuntimeError("audit counts do not match current evidence")
    if audit["ok"] is not True or audit["errors"] != []:
        raise RuntimeError("audit did not prove a complete clean result")


def _validate_results(
    results: Mapping[str, CommandResult],
    *,
    registry: SourceRegistry,
    lock: SourceLock,
) -> Mapping[str, CommandResult]:
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
    for name in ("diff_check", "boundary_large_files"):
        if results[name].stdout or results[name].stderr:
            raise RuntimeError(f"{name} verification produced unexpected output")
    tracked = _parse_tracked_paths(results["boundary_paths"].stdout)
    if results["boundary_paths"].stderr:
        raise RuntimeError("boundary_paths verification produced stderr")
    forbidden = forbidden_tracked_paths(tracked)
    if forbidden:
        raise RuntimeError(f"boundary_paths found forbidden tracked paths: {forbidden}")
    paths = sum(len(entry.path_statuses) for entry in lock.entries)
    discovered = sum(
        entry.license_status is LicenseStatus.DISCOVERED for entry in lock.entries
    )
    _validate_audit(
        results["audit"].stdout,
        registry_entries=len(registry.repositories),
        lock_entries=len(lock.entries),
        selected_paths=paths,
        discovered_licenses=discovered,
        tracked_files=len(tracked),
    )
    safety_lines = [
        line for line in results["safety"].stdout.splitlines() if line.strip()
    ]
    try:
        safety = json.loads(safety_lines[-1]) if safety_lines else None
    except json.JSONDecodeError as exc:
        raise RuntimeError("safety verification did not emit valid JSON") from exc
    if (
        not isinstance(safety, dict)
        or set(safety) != {"simulation_only", "remote_enabled"}
        or type(safety["simulation_only"]) is not bool
        or type(safety["remote_enabled"]) is not bool
        or safety["simulation_only"] is not True
        or safety["remote_enabled"] is not False
    ):
        raise RuntimeError("safety verification did not prove simulation-only state")
    return results


def _visible_output(value: str) -> str:
    return value.replace("\0", "\\0")


def _command_block(result: CommandResult) -> str:
    text = (
        f"$ {' '.join(result.command)}\n"
        f"stdout:\n{_visible_output(result.stdout) or '(empty)'}\n"
        f"stderr:\n{_visible_output(result.stderr) or '(empty)'}\n"
        f"exit: {result.returncode}"
    )
    return f"<pre>{html.escape(text)}</pre>"


def validate_evidence(
    *,
    registry_bytes: bytes,
    lock_bytes: bytes,
    attempt_bytes: bytes,
    expected_registry_entries: int | None = None,
) -> ValidatedEvidence:
    """Validate a stable immutable evidence snapshot before commands run."""
    registry = _load_registry(registry_bytes)
    lock = _load_lock(lock_bytes)
    errors = validate_lock(registry, lock, require_complete=True)
    if errors:
        raise ValueError(f"complete P2 lock validation failed: {'; '.join(errors)}")
    if expected_registry_entries is not None and len(registry.repositories) != expected_registry_entries:
        raise ValueError(
            f"registry contains {len(registry.repositories)} entries, "
            f"expected {expected_registry_entries}"
        )
    try:
        attempt_text = attempt_bytes.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("attempt log is not UTF-8") from exc
    attempts = parse_attempt_log(
        attempt_text,
        expected_registry_sha256=registry.registry_sha256,
        registry_names=tuple(entry.name for entry in registry.repositories),
    )
    publications = [attempt for attempt in attempts.attempts if attempt.published_lock]
    if len(publications) != 1 or publications[0] is not attempts.attempts[-1]:
        raise ValueError("attempt log must end with exactly one successful publication")
    final = publications[0]
    lock_digest = hashlib.sha256(lock_bytes).hexdigest()
    if final.lock_sha256_after != lock_digest:
        raise ValueError("published attempt lock digest does not match current lock bytes")
    generated_at = canonical_utc(lock.generated_at, "lock.generated_at")
    if final.finished_at_utc is None or not (
        final.started_at_utc <= generated_at <= final.finished_at_utc
    ):
        raise ValueError("lock generated_at must fall within final attempt")
    timestamps = tuple(
        canonical_utc(entry.retrieved_at, f"lock entry {entry.name} retrieved_at")
        for entry in lock.entries
    )
    return ValidatedEvidence(registry, lock, attempts, lock_digest, timestamps)


def build_report(
    *,
    registry_bytes: bytes,
    lock_bytes: bytes,
    attempt_bytes: bytes,
    implementation_sha: str,
    command_results: Mapping[str, CommandResult],
    physical_deployment_allowed: bool,
    remote_enabled: bool,
    expected_registry_entries: int | None = None,
) -> str:
    """Validate immutable snapshots and render a P2 report."""
    require_safe_state(
        physical_deployment_allowed=physical_deployment_allowed,
        remote_enabled=remote_enabled,
    )
    evidence = validate_evidence(
        registry_bytes=registry_bytes,
        lock_bytes=lock_bytes,
        attempt_bytes=attempt_bytes,
        expected_registry_entries=expected_registry_entries,
    )
    registry = evidence.registry
    lock = evidence.lock
    attempts = evidence.attempts
    lock_digest = evidence.lock_digest
    timestamps = evidence.retrieval_timestamps
    results = _validate_results(command_results, registry=registry, lock=lock)
    statuses = [status for entry in lock.entries for status in entry.path_statuses.values()]
    licenses = [entry.license_status for entry in lock.entries]
    evidence = "\n\n".join(_command_block(results[name]) for name in REQUIRED_COMMANDS)
    history = html.escape(attempts.source_text.rstrip())
    return f"""# P2 Run Report

## Executive result

The complete public-source metadata lock passed the offline P2 gate.

## Evidence base

- Implementation/evidence-base Git SHA: `{implementation_sha}`
- Registry SHA-256: `{registry.registry_sha256}`
- Complete lock SHA-256: `{lock_digest}`
- Retrieval interval: `{min(timestamps)}` through `{max(timestamps)}`
- Registry entries: `{len(registry.repositories)}`
- Lock entries: `{len(lock.entries)}`; metadata RESOLVED: `{sum(entry.metadata_status is MetadataStatus.RESOLVED for entry in lock.entries)}`
- Selected paths: `{len(statuses)}` (`{statuses.count(PathStatus.EXISTS)}` EXISTS, `{statuses.count(PathStatus.MISSING)}` MISSING)
- Licenses: `{licenses.count(LicenseStatus.DISCOVERED)}` DISCOVERED, `{licenses.count(LicenseStatus.UNKNOWN)}` UNKNOWN, `{licenses.count(LicenseStatus.UNAVAILABLE)}` UNAVAILABLE
- Physical deployment allowed: `false`; remote execution enabled: `false`

## Exact durable live-attempt history

<pre>{history}</pre>

The final successful attempt covers all `{len(registry.repositories)}` unique registry
entries and binds its `lock_sha256_after` to the current lock bytes. Every failed
window records either verified lock absence or identical before/after lock digests.

## Offline verification evidence

{evidence}

## Repository boundary

- The complete NUL-delimited tracked inventory passed secret, checkout, and model checks.
- Unapproved files larger than 100 MiB: none.
- `git diff --check`: exit 0, empty output.
- No network or live resolver command was run by this report generator.

## Scope and limitations

- GitHub license metadata is an observed upstream signal, not a legal conclusion.
- `MISSING` selected paths are explicit compatibility evidence, not guesses.
- No physical deployment, remote execution, checkout, or experiment ran.

## Highest-value next bounded action

Run the P3 source compatibility audit against this immutable lock before adapting
any upstream source or beginning empirical experiments.
"""
