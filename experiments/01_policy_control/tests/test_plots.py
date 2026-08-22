from __future__ import annotations

import importlib


evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")


def _rows():
    return tuple(
        evaluate.PlotRow(
            stack, seed, f"condition-{seed}", 10, 300, 2, "NONE",
            0.5 + seed, 0.01 + seed, 2.0 + seed, 0.3, (0.1, 0.2, 0.15), True,
        )
        for stack in ("P1", "P2", "P3")
        for seed in (2, 1)
    )


def test_rendered_plot_bytes_are_deterministic_and_complete() -> None:
    first = evaluate.render_svg_plots(_rows(), ("P2", "P3"))
    second = evaluate.render_svg_plots(tuple(reversed(_rows())), ("P2", "P3"))
    assert first == second
    assert tuple(first) == (
        "recovery-vs-latency.svg", "tracking-error-vs-rate.svg", "joint-jerk.svg",
        "action-age.svg", "timeline.svg",
    )
    assert all(payload.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"') and payload.endswith(b"</svg>\n") for payload in first.values())


def test_write_plots_is_create_only_and_exact_reissue_skips(tmp_path) -> None:
    paths = evaluate.write_svg_plots(tmp_path, _rows(), ("P2",))
    before = {path.name: path.read_bytes() for path in paths}
    assert evaluate.write_svg_plots(tmp_path, tuple(reversed(_rows())), ("P2",)) == paths
    assert before == {path.name: path.read_bytes() for path in paths}
    changed = list(_rows())
    changed[0] = evaluate.PlotRow("P1", 2, "condition-2", 10, 300, 2, "NONE", 9.0, 0.01, 2.0, 0.3, (0.1,), True)
    try:
        evaluate.write_svg_plots(tmp_path, changed, ("P2",))
    except FileExistsError:
        pass
    else:
        raise AssertionError("changed plot reissue must fail")
