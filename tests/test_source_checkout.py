from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

import pytest

from reflect.source_checkout import (
    CheckoutCommandResult,
    CheckoutSpec,
    SparseCheckoutError,
    checkout_sparse,
    eligible_checkout_specs,
)
from reflect.source_evidence import CheckoutEvidence, write_evidence_create_only
from reflect.source_fetch import lock_yaml_bytes
from reflect.sources import (
    LicenseStatus,
    LockedEntry,
    MetadataStatus,
    PathStatus,
    SourceLock,
    load_registry,
)
from scripts.fetch_reference import main as fetch_main


SHA = "a" * 40
ELIGIBLE = {
    "mujoco_mpc",
    "mujoco_menagerie",
    "mjctrl",
    "act",
    "lerobot",
    "openpi",
    "behaviortree_cpp",
    "navigation2",
}


def complete_lock(*, missing: tuple[str, str] | None = None) -> tuple[Any, SourceLock]:
    registry = load_registry(Path("references/repos.yaml"))
    entries = []
    for index, source in enumerate(registry.repositories):
        statuses = {
            path: (
                PathStatus.MISSING.value
                if missing == (source.name, path)
                else PathStatus.EXISTS.value
            )
            for path in source.selected_paths
        }
        entries.append(
            LockedEntry(
                name=source.name,
                url=source.url,
                default_branch="main",
                commit_sha=f"{index + 1:040x}",
                retrieved_at="2026-08-22T00:00:00Z",
                metadata_evidence={"tree": "https://api.github.com/example"},
                license_spdx="MIT",
                license_status=LicenseStatus.DISCOVERED,
                license_evidence_url="https://example.invalid/license",
                path_statuses=statuses,
                path_evidence_urls={
                    path: "https://api.github.com/example" for path in source.selected_paths
                },
                metadata_status=MetadataStatus.RESOLVED,
            )
        )
    return registry, SourceLock(
        registry_sha256=registry.registry_sha256,
        generated_at="2026-08-22T00:00:00Z",
        entries=tuple(entries),
    )


class RecordingRunner:
    def __init__(self, *, replacement_root: Path | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.replacement_root = replacement_root
        self.sha = SHA

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        input_bytes: bytes | None = None,
    ) -> CheckoutCommandResult:
        self.calls.append(
            {
                "argv": argv,
                "cwd": cwd,
                "env": env,
                "timeout": timeout,
                "input": input_bytes,
            }
        )
        if argv[:3] == ("git", "init", "--quiet"):
            checkout = cwd / argv[3]
            (checkout / ".git" / "info").mkdir(parents=True)
        checkout_name = next(
            (argv[index + 1] for index, item in enumerate(argv[:-1]) if item == "-C"),
            None,
        )
        checkout = cwd / checkout_name if checkout_name is not None else None
        command = argv[-1]
        if "fetch" in argv:
            self.sha = argv[-1]
        if "sparse-checkout" in argv and "set" in argv:
            assert checkout is not None and input_bytes is not None
            (checkout / ".git" / "info" / "sparse-checkout").write_bytes(input_bytes)
        elif "checkout" in argv and argv[-2] == "--detach":
            assert checkout is not None
            patterns = (checkout / ".git" / "info" / "sparse-checkout").read_text().splitlines()
            for pattern in patterns:
                if pattern == "*.py":
                    (checkout / "root.py").write_text("value = 1\n")
                elif "*" not in pattern and "?" not in pattern:
                    target = checkout / pattern
                    if Path(pattern).suffix:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text("fixture\n")
                    else:
                        target.mkdir(parents=True, exist_ok=True)
                        (target / "fixture.txt").write_text("fixture\n")
            if self.replacement_root is not None:
                moved = cwd.with_name(cwd.name + "-moved")
                cwd.rename(moved)
                self.replacement_root.mkdir()
        if argv[-2:] == ("rev-parse", "HEAD"):
            return CheckoutCommandResult(0, (self.sha + "\n").encode(), b"", 0)
        if "status" in argv:
            return CheckoutCommandResult(0, b"", b"", 0)
        if argv[-2:] == ("sparse-checkout", "list"):
            assert checkout is not None
            return CheckoutCommandResult(
                0,
                (checkout / ".git" / "info" / "sparse-checkout").read_bytes(),
                b"",
                0,
            )
        return CheckoutCommandResult(0, b"", b"", 17)


def test_selector_returns_exact_eight_and_excludes_locked_missing_path() -> None:
    registry, lock = complete_lock(missing=("mjctrl", "README.md"))
    specs = eligible_checkout_specs(registry, lock, experiment="01_policy_control")
    assert {spec.name for spec in specs} == {
        "mujoco_mpc",
        "mujoco_menagerie",
        "mjctrl",
    }
    all_specs = tuple(
        spec
        for experiment in ("01_policy_control", "02_action_chunks", "03_recovery")
        for spec in eligible_checkout_specs(registry, lock, experiment=experiment)
    )
    assert {spec.name for spec in all_specs} == ELIGIBLE
    mjctrl = next(spec for spec in all_specs if spec.name == "mjctrl")
    assert mjctrl.patterns == ("*.py",)
    assert "README.md" not in mjctrl.patterns


def test_selector_requires_exactly_one_selector_and_complete_lock() -> None:
    registry, lock = complete_lock()
    with pytest.raises(SparseCheckoutError, match="exactly one"):
        eligible_checkout_specs(registry, lock)
    with pytest.raises(SparseCheckoutError, match="exactly one"):
        eligible_checkout_specs(registry, lock, name="mjctrl", experiment="01_policy_control")
    incomplete = replace(lock, entries=lock.entries[:-1])
    with pytest.raises(SparseCheckoutError, match="complete"):
        eligible_checkout_specs(registry, incomplete, name="mjctrl")
    with pytest.raises(SparseCheckoutError, match="eligible"):
        eligible_checkout_specs(registry, lock, name="mujoco")


@pytest.mark.parametrize("pattern", ["/absolute", "../escape", "a/../b", "bad\npath", "bad\0path"])
def test_selector_rejects_unsafe_sparse_patterns(pattern: str) -> None:
    registry, lock = complete_lock()
    source = next(entry for entry in registry.repositories if entry.name == "mjctrl")
    mutated_source = replace(source, selected_paths=(pattern,))
    mutated_registry = replace(
        registry,
        repositories=tuple(
            mutated_source if entry.name == "mjctrl" else entry
            for entry in registry.repositories
        ),
    )
    locked = next(entry for entry in lock.entries if entry.name == "mjctrl")
    mutated_locked = replace(
        locked,
        path_statuses={pattern: PathStatus.EXISTS.value},
        path_evidence_urls={pattern: "https://api.github.com/example"},
    )
    mutated_lock = replace(
        lock,
        entries=tuple(
            mutated_locked if entry.name == "mjctrl" else entry for entry in lock.entries
        ),
    )
    with pytest.raises(SparseCheckoutError, match="path"):
        eligible_checkout_specs(mutated_registry, mutated_lock, name="mjctrl")


def test_checkout_uses_fixed_git_commands_locked_sha_and_existing_patterns(tmp_path: Path) -> None:
    spec = CheckoutSpec(
        registry_sha256="9" * 64,
        name="example",
        url="https://github.com/example/project",
        commit_sha=SHA,
        requested_paths=("*.py", "gone"),
        patterns=("*.py",),
    )
    runner = RecordingRunner()
    result = checkout_sparse(spec, tmp_path / "external", runner)
    assert result.commit_sha == SHA
    assert result.patterns == ("*.py",)
    assert (result.destination / "root.py").is_file()
    assert not (result.destination / "gone").exists()
    assert all(call["timeout"] > 0 for call in runner.calls)
    assert all(call["env"]["GIT_TERMINAL_PROMPT"] == "0" for call in runner.calls)
    assert all("GIT_CONFIG_GLOBAL" in call["env"] for call in runner.calls)
    assert any(call["input"] == b"*.py\n" for call in runner.calls)
    assert all("shell" not in call for call in runner.calls)
    flattened = [item for call in runner.calls for item in call["argv"]]
    assert SHA in flattened
    assert "gone" not in flattened


def test_checkout_refuses_symlinked_root_and_intermediate_without_touching_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "external"
    root.symlink_to(outside, target_is_directory=True)
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    with pytest.raises(SparseCheckoutError, match="symlink|directory"):
        checkout_sparse(spec, root, RecordingRunner())
    assert tuple(outside.iterdir()) == ()

    safe = tmp_path / "safe"
    safe.mkdir()
    (safe / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SparseCheckoutError, match="symlink|directory"):
        checkout_sparse(spec, safe / "linked" / "external", RecordingRunner())
    assert tuple(outside.iterdir()) == ()


def test_checkout_detects_root_inode_replacement_and_does_not_publish_outside(tmp_path: Path) -> None:
    root = tmp_path / "external"
    outside = tmp_path / "replacement"
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    with pytest.raises(SparseCheckoutError, match="changed"):
        checkout_sparse(spec, root, RecordingRunner(replacement_root=outside))
    assert not (outside / "example").exists()


def test_checkout_refuses_symlink_dirty_or_mismatched_existing_destination(tmp_path: Path) -> None:
    root = tmp_path / "external"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "example").symlink_to(outside, target_is_directory=True)
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    with pytest.raises(SparseCheckoutError, match="destination"):
        checkout_sparse(spec, root, RecordingRunner())
    assert tuple(outside.iterdir()) == ()


def test_checkout_reuses_only_clean_matching_existing_destination(tmp_path: Path) -> None:
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    root = tmp_path / "external"
    first = checkout_sparse(spec, root, RecordingRunner())
    second = checkout_sparse(spec, root, RecordingRunner())
    assert second.reused is True
    assert second.destination == first.destination


def test_checkout_evidence_is_canonical_create_only_and_mode_0600(tmp_path: Path) -> None:
    evidence = CheckoutEvidence.create(
        registry_sha256="9" * 64,
        repository="example",
        url="https://github.com/example/project",
        locked_sha=SHA,
        patterns=("*.py",),
        commands=(("git", "init", "--quiet", ".example.partial"),),
        statuses=(0,),
        download_bytes=17,
        disk_bytes=23,
        outcome="PASS",
        blocker=None,
        content_hashes={"root.py": hashlib.sha256(b"value = 1\n").hexdigest()},
    )
    path = tmp_path / "fragments" / "example.json"
    write_evidence_create_only(path, evidence)
    payload = path.read_bytes()
    assert payload.endswith(b"\n")
    assert json.loads(payload)["evidence_sha256"] == evidence.evidence_sha256
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_evidence_create_only(path, evidence)


def test_sparse_cli_requires_explicit_fragment_directory() -> None:
    with pytest.raises(SystemExit):
        fetch_main(["--name", "mjctrl", "--sparse-checkout"])
    with pytest.raises(SystemExit):
        fetch_main(["--experiment", "01_policy_control", "--sparse-checkout"])


def test_sparse_cli_audits_lock_writes_one_fragment_and_preserves_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry, lock = complete_lock()
    lock_path = tmp_path / "repos.lock.yaml"
    lock_path.write_bytes(lock_yaml_bytes(lock))
    before = lock_path.read_bytes()
    fragments = tmp_path / "fragments"
    result = fetch_main(
        [
            "--name",
            "mujoco_mpc",
            "--sparse-checkout",
            "--fragment-dir",
            os.fspath(fragments),
        ],
        root=tmp_path,
        registry_path=Path("references/repos.yaml"),
        lock_path=lock_path,
        checkout_runner=RecordingRunner(),
    )
    assert result == 0
    assert lock_path.read_bytes() == before
    paths = tuple(fragments.iterdir())
    assert tuple(path.name for path in paths) == ("mujoco_mpc-checkout.json",)
    evidence = json.loads(paths[0].read_text())
    assert evidence["evidence_type"] == "CHECKOUT"
    assert evidence["registry_sha256"] == registry.registry_sha256
    assert evidence["repository"] == "mujoco_mpc"
    output = json.loads(capsys.readouterr().out)
    assert output == [
        {
            "destination": os.fspath(tmp_path / "external" / "mujoco_mpc"),
            "evidence_sha256": evidence["evidence_sha256"],
            "repository": "mujoco_mpc",
            "reused": False,
        }
    ]
