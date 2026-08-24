from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib
import json

import pytest


c = importlib.import_module("experiments.03_recovery.src.contracts")


def test_closed_enums_are_exact() -> None:
    assert tuple(item.value for item in c.Architecture) == ("R0", "R1", "R2", "R3")
    assert tuple(item.value for item in c.RecoveryLevel) == ("NONE", "CONTROL", "MOTION", "SEMANTIC", "SAFE_ABORT")
    assert tuple(item.value for item in c.ScenarioDomain) == ("ANCHOR", "CONTROL", "MOTION", "SEMANTIC")
    assert tuple(item.value for item in c.TerminalDisposition) == ("SUCCESS", "SAFE_ABORT", "INVALID_EVIDENCE", "NOT_RUN")
    with pytest.raises(ValueError):
        c.Architecture("R4")


def test_fixed_t3_memory_has_canonical_bytes_and_hash() -> None:
    snapshot = c.base_memory_snapshot()
    assert snapshot.schema_id == "T3_LIVE_BELIEF_V1"
    assert snapshot.to_bytes() == snapshot.to_bytes()
    assert json.loads(snapshot.to_bytes())["schema_id"] == "T3_LIVE_BELIEF_V1"
    assert c.sha256_bytes(snapshot.to_bytes()) == snapshot.sha256
    with pytest.raises(FrozenInstanceError):
        snapshot.version = 2


@pytest.mark.parametrize(
    ("constructor", "kwargs"),
    [
        (c.MemoryFact, {"object_id": "target\N{SNOWMAN}"}),
        (c.MemoryFact, {"confidence": float("nan")}),
        (c.MotionCommand, {"command_sha256": "not-a-hash"}),
        (c.EpisodeSpec, {"episode_id": "contains space"}),
    ],
)
def test_rows_reject_non_ascii_nonfinite_bad_hashes_and_identity(constructor: object, kwargs: dict[str, object]) -> None:
    defaults = {
        c.MemoryFact: dict(object_id="object-a", semantic_label="service-panel", affordance="inspect", restrictions=("AUTHORIZED",), pose_xy=(0.55, 0.08), available=True, observed_tick=0, confidence=1.0, provenance="scenario-record", stale=False, unknown=False),
        c.MotionCommand: dict(command_id="command-000", object_id="object-a", target_xy=(0.55, 0.08), feasible=True, trajectory_sha256="0" * 64, command_sha256="1" * 64, generated_tick=0),
        c.EpisodeSpec: dict(episode_id="primary-R0-anchor-none-20261601", architecture=c.Architecture.LOCAL_ONLY, scenario_id="anchor-none", scenario_domain=c.ScenarioDomain.ANCHOR, seed=20261601, controller_id="P6-res0p5-slew48", sensitivity=False),
    }
    values = defaults[constructor] | kwargs
    with pytest.raises(ValueError):
        constructor(**values)


def test_episode_spec_has_no_hidden_scorer_input() -> None:
    with pytest.raises(TypeError):
        c.EpisodeSpec(
            episode_id="primary-R3-control-impulse-20261601",
            architecture=c.Architecture.LAYER_MATCHED,
            scenario_id="control-impulse",
            scenario_domain=c.ScenarioDomain.CONTROL,
            seed=20261601,
            controller_id="P6-res0p5-slew48",
            sensitivity=False,
            hidden_cause="CONTROL",  # type: ignore[call-arg]
        )


def test_every_immutable_row_round_trips_through_canonical_wire() -> None:
    memory = c.base_memory_snapshot()
    request = c.SkillRequest("skill-000", "service-panel", "inspect", "object-a", ((0.50, 0.60), (0.02, 0.14)), ("AUTHORIZED",), memory.version, "eef_within_0p025m")
    command = c.MotionCommand.from_target("command-000", "object-a", (0.55, 0.08), True, 0)
    failure = c.ObservableFailure(False, True, True, True, True, c.RecoveryLevel.NONE, command.command_sha256, False, 750)
    budget = c.RecoveryBudget.initial(command.command_sha256)
    decision = c.RecoveryDecision(c.RecoveryLevel.NONE, "NO_FAILURE", budget, 750, command.command_sha256)
    spec = c.EpisodeSpec("primary-R3-anchor-none-20261601", c.Architecture.LAYER_MATCHED, "anchor-none", c.ScenarioDomain.ANCHOR, 20261601, "P6-res0p5-slew48", False)
    for row in (memory.facts[0], memory, request, command, failure, budget, decision, spec):
        assert json.loads(c.canonical_bytes(row))
