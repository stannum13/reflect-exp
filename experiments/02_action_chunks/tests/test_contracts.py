from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib

import pytest

contracts = importlib.import_module("experiments.02_action_chunks.src.contracts")
CellIdentity = contracts.CellIdentity
FaultId = contracts.FaultId
ProtocolId = contracts.ProtocolId
RequestPlan = contracts.RequestPlan
VectorId = contracts.VectorId


def test_closed_identifiers_are_exact() -> None:
    assert tuple(member.value for member in ProtocolId) == tuple("ABCDEFG")
    assert tuple(member.value for member in VectorId) == ("v0", "v1", "v2")
    assert tuple(member.value for member in FaultId) == (
        "NONE",
        "DROP",
        "OLD_AFTER_NEWER",
        "PAUSE",
        "ALTERNATIVE",
        "DISCONTINUITY",
        "STATIONARY_CONTROL",
    )


def test_identity_is_frozen_ordered_and_strict() -> None:
    first = CellIdentity("tuning", "P2", ProtocolId.A, None, 7, 25, (51,), FaultId.NONE)
    second = CellIdentity("tuning", "P2", ProtocolId.A, None, 7, 25, (51, 1052), FaultId.NONE)
    assert first < second
    with pytest.raises(FrozenInstanceError):
        first.seed = 8  # type: ignore[misc]
    with pytest.raises(ValueError, match="bool|integer"):
        CellIdentity("tuning", "P2", ProtocolId.A, None, True, 25, (51,), FaultId.NONE)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="vector"):
        CellIdentity("tuning", "P2", ProtocolId.A, VectorId.V0, 7, 25, (51,), FaultId.NONE)
    with pytest.raises(ValueError, match="move schedule"):
        CellIdentity("tuning", "P2", ProtocolId.B, VectorId.V0, 7, 25, (52,), FaultId.NONE)


def test_request_plan_enforces_cutoff_capacity_and_terminal_bound() -> None:
    plan = RequestPlan(0, 2500, 2850, 3000, 3000, 3125, 1)
    assert (plan.actual_delivery_tick, plan.expiry_tick) == (3000, 3125)
    with pytest.raises(ValueError, match="cutoff"):
        RequestPlan(0, 2501, 2851, 2851, 2851, 2976, 1)
    with pytest.raises(ValueError, match="capacity"):
        RequestPlan(0, 50, 75, 75, 75, 200, 2, queue_capacity=1)
    with pytest.raises(ValueError, match="bool|integer"):
        RequestPlan(True, 50, 75, 75, 75, 200, 1)  # type: ignore[arg-type]
