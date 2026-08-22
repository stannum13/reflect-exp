from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

import pytest

import reflect.source_checkout as checkout_module
import reflect.source_evidence as evidence_module
from reflect.source_checkout import (
    CheckoutCommandResult,
    CheckoutSpec,
    SparseCheckoutError,
    SubprocessCheckoutRunner,
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
    def __init__(
        self,
        *,
        replacement_root: Path | None = None,
        fail_on: str | None = None,
        raise_on: str | None = None,
        git_object_bytes: int = 0,
        wrong_head: bool = False,
        dirty: bool = False,
        fetch_download_bytes: int = 17,
        invalid_head: bool = False,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.replacement_root = replacement_root
        self.sha = SHA
        self.fail_on = fail_on
        self.raise_on = raise_on
        self.git_object_bytes = git_object_bytes
        self.wrong_head = wrong_head
        self.dirty = dirty
        self.fetch_download_bytes = fetch_download_bytes
        self.invalid_head = invalid_head

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        input_bytes: bytes | None = None,
        max_download_bytes: int = 512 * 1024 * 1024,
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
        if self.raise_on is not None and self.raise_on in argv:
            raise RuntimeError("unexpected runner failure")
        if self.fail_on is not None and self.fail_on in argv:
            return CheckoutCommandResult(7, b"", b"failed", 19)
        if argv[:3] == ("git", "init", "--quiet"):
            checkout = cwd / argv[3]
            assert stat.S_IMODE(checkout.stat().st_mode) == 0o700
            (checkout / ".git" / "info").mkdir(parents=True, exist_ok=True)
        checkout_name = next(
            (argv[index + 1] for index, item in enumerate(argv[:-1]) if item == "-C"),
            None,
        )
        checkout = cwd / checkout_name if checkout_name is not None else None
        command = argv[-1]
        if "fetch" in argv:
            self.sha = argv[-1]
            if checkout is not None and self.git_object_bytes:
                target = checkout / ".git" / "objects" / "pack"
                target.mkdir(parents=True)
                (target / "fixture.pack").write_bytes(b"x" * self.git_object_bytes)
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
            if self.invalid_head:
                return CheckoutCommandResult(0, b"\xff", b"", 0)
            head = "b" * 40 if self.wrong_head else self.sha
            return CheckoutCommandResult(0, (head + "\n").encode(), b"", 0)
        if "status" in argv:
            return CheckoutCommandResult(0, b"dirty\0" if self.dirty else b"", b"", 0)
        if argv[-2:] == ("sparse-checkout", "list"):
            assert checkout is not None
            return CheckoutCommandResult(
                0,
                (checkout / ".git" / "info" / "sparse-checkout").read_bytes(),
                b"",
                0,
            )
        return CheckoutCommandResult(
            0, b"", b"", self.fetch_download_bytes if "fetch" in argv else 0
        )


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


def test_checkout_strips_ambient_git_hooks_fsmonitor_and_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "/tmp/hostile")
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.invalid")
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    runner = RecordingRunner()
    checkout_sparse(spec, tmp_path / "external", runner)
    assert all(not any(key.startswith("GIT_CONFIG_") and key not in {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"} for key in call["env"]) for call in runner.calls)
    assert all("HTTPS_PROXY" not in call["env"] for call in runner.calls)
    assert all("core.hooksPath=/dev/null" in call["argv"] for call in runner.calls[1:])
    assert all("core.fsmonitor=false" in call["argv"] for call in runner.calls[1:])


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
    assert tuple(outside.iterdir()) == ()
    moved = root.with_name(root.name + "-moved")
    assert tuple(moved.iterdir()) == ()


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
    with pytest.raises(SparseCheckoutError, match="dirty"):
        checkout_sparse(spec, root, RecordingRunner(dirty=True))
    with pytest.raises(SparseCheckoutError, match="HEAD"):
        checkout_sparse(spec, root, RecordingRunner(wrong_head=True))
    (root / "example").chmod(0o755)
    with pytest.raises(SparseCheckoutError, match="0700|mode"):
        checkout_sparse(spec, root, RecordingRunner())


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


def test_failure_evidence_has_closed_matrix_and_atomic_publish_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="outcome"):
        CheckoutEvidence.create(
            registry_sha256="9" * 64, repository="example", url="https://github.com/example/project",
            locked_sha=SHA, patterns=("*.py",), commands=(("git", "fetch"),), statuses=(0,),
            download_bytes=1, disk_bytes=1, outcome="UNKNOWN", blocker=None,
            content_hashes={"root.py": "8" * 64},
        )
    failure = CheckoutEvidence.create(
        registry_sha256="9" * 64, repository="example", url="https://github.com/example/project",
        locked_sha=SHA, patterns=("*.py",), commands=(("git", "fetch"),), statuses=(7,),
        download_bytes=19, disk_bytes=0, outcome="FAIL", blocker="fetch returned 7",
        content_hashes={},
    )
    destination = tmp_path / "fragments" / "failure.json"

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("publication failed")

    monkeypatch.setattr(evidence_module.os, "link", fail_link)
    with pytest.raises(OSError, match="publication"):
        write_evidence_create_only(destination, failure)
    assert not destination.exists()
    assert tuple(destination.parent.iterdir()) == ()


def test_retained_git_objects_count_toward_disk_cap_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checkout_module, "_MAX_DISK_BYTES", 64)
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    root = tmp_path / "external"
    with pytest.raises(SparseCheckoutError, match="disk byte ceiling"):
        checkout_sparse(spec, root, RecordingRunner(git_object_bytes=65))
    assert tuple(root.iterdir()) == ()


def test_download_cap_plus_one_and_failed_publication_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    monkeypatch.setattr(checkout_module, "_MAX_DOWNLOAD_BYTES", 64)
    root = tmp_path / "external"
    with pytest.raises(SparseCheckoutError, match="download"):
        checkout_sparse(spec, root, RecordingRunner(fetch_download_bytes=65))
    assert tuple(root.iterdir()) == ()
    monkeypatch.setattr(checkout_module, "_MAX_DOWNLOAD_BYTES", 512 * 1024 * 1024)

    def fail_publish(*args: object) -> None:
        raise SparseCheckoutError("publication failed")

    monkeypatch.setattr(checkout_module, "_publish_no_replace", fail_publish)
    with pytest.raises(SparseCheckoutError, match="publication"):
        checkout_sparse(spec, root, RecordingRunner())
    assert tuple(root.iterdir()) == ()


def test_partial_cleanup_covers_unexpected_runner_exception(tmp_path: Path) -> None:
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    root = tmp_path / "external"
    with pytest.raises(SparseCheckoutError, match="runner failed"):
        checkout_sparse(spec, root, RecordingRunner(raise_on="remote"))
    assert tuple(root.iterdir()) == ()


def test_subprocess_runner_accounts_conservative_fetch_growth(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "partial"
    (checkout / ".git").mkdir(parents=True)

    result = SubprocessCheckoutRunner().run(
        (
            sys.executable, "-c",
            "from pathlib import Path;Path('partial/.git/pack').write_bytes(b'x'*37)",
            "-C", "partial", "fetch",
        ),
        cwd=tmp_path, env={}, timeout=1, max_download_bytes=1024 * 1024,
    )
    assert result.download_bytes >= 37


def test_subprocess_runner_streams_success_and_stops_failed_no_pack_at_cap() -> None:
    runner = SubprocessCheckoutRunner()
    success = runner.run(
        (sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'ok')"),
        cwd=Path.cwd(), env=dict(os.environ), timeout=5, max_download_bytes=64,
    )
    assert success.returncode == 0
    assert success.stdout == b"ok"
    assert success.download_bytes == 2
    capped = runner.run(
        (sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*65);sys.stdout.flush()"),
        cwd=Path.cwd(), env=dict(os.environ), timeout=5, max_download_bytes=64,
    )
    assert capped.returncode != 0
    assert capped.download_bytes == 65
    assert len(capped.stdout) == 65


def test_post_publish_root_drift_cleans_exact_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "external"
    replacement = tmp_path / "replacement"
    real_publish = checkout_module._publish_no_replace

    def drifting_publish(descriptor: int, source: str, destination: str) -> None:
        real_publish(descriptor, source, destination)
        root.rename(root.with_name(root.name + "-moved"))
        replacement.mkdir()
        replacement.rename(root)

    monkeypatch.setattr(checkout_module, "_publish_no_replace", drifting_publish)
    spec = CheckoutSpec("9" * 64, "example", "https://github.com/example/project", SHA, ("README.md",), ("README.md",))
    with pytest.raises(SparseCheckoutError, match="changed"):
        checkout_sparse(spec, root, RecordingRunner())
    assert tuple(root.iterdir()) == ()
    assert tuple(root.with_name(root.name + "-moved").iterdir()) == ()


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


def test_sparse_cli_writes_immutable_failure_fragment(tmp_path: Path) -> None:
    _, lock = complete_lock()
    lock_path = tmp_path / "repos.lock.yaml"
    lock_path.write_bytes(lock_yaml_bytes(lock))
    fragments = tmp_path / "fragments"
    with pytest.raises(SparseCheckoutError, match="returned 7"):
        fetch_main(
            ["--name", "mujoco_mpc", "--sparse-checkout", "--fragment-dir", os.fspath(fragments)],
            root=tmp_path, registry_path=Path("references/repos.yaml"), lock_path=lock_path,
            checkout_runner=RecordingRunner(fail_on="fetch"),
        )
    payload = json.loads((fragments / "mujoco_mpc-checkout.json").read_text())
    assert payload["outcome"] == "FAIL"
    assert payload["statuses"][-1] == 7
    assert payload["blocker"]
    with pytest.raises(FileExistsError):
        fetch_main(
            ["--name", "mujoco_mpc", "--sparse-checkout", "--fragment-dir", os.fspath(fragments)],
            root=tmp_path, registry_path=Path("references/repos.yaml"), lock_path=lock_path,
            checkout_runner=RecordingRunner(fail_on="fetch"),
        )


@pytest.mark.parametrize(
    "runner,setup",
    [
        (RecordingRunner(invalid_head=True), None),
        (RecordingRunner(raise_on="remote"), None),
        (RecordingRunner(), "symlink-root"),
        (RecordingRunner(), "destination-collision"),
    ],
)
def test_sparse_cli_normalizes_preflight_decode_unexpected_and_collision_failures(
    tmp_path: Path, runner: RecordingRunner, setup: str | None
) -> None:
    _, lock = complete_lock()
    lock_path = tmp_path / "repos.lock.yaml"
    lock_path.write_bytes(lock_yaml_bytes(lock))
    outside = tmp_path / "outside"
    if setup == "symlink-root":
        outside.mkdir()
        (tmp_path / "external").symlink_to(outside, target_is_directory=True)
    elif setup == "destination-collision":
        (tmp_path / "external").mkdir()
        (tmp_path / "external" / "mujoco_mpc").write_text("collision")
    fragments = tmp_path / "fragments"
    with pytest.raises(SparseCheckoutError):
        fetch_main(
            ["--name", "mujoco_mpc", "--sparse-checkout", "--fragment-dir", os.fspath(fragments)],
            root=tmp_path, registry_path=Path("references/repos.yaml"), lock_path=lock_path,
            checkout_runner=runner,
        )
    payload = json.loads((fragments / "mujoco_mpc-checkout.json").read_text())
    assert payload["outcome"] == "FAIL"
    assert len(payload["commands"]) == len(payload["statuses"])
    if setup in {"symlink-root", "destination-collision"}:
        assert payload["commands"] == payload["statuses"] == []
    assert payload["blocker"]
    assert tuple(outside.iterdir()) == () if outside.exists() else True
