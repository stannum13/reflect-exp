from __future__ import annotations

import numpy as np
import mujoco


def test_mujoco_model_seam_is_headless_and_steps_once() -> None:
    model = mujoco.MjModel.from_xml_string(
        "<mujoco><worldbody><body><joint name='hinge' type='hinge'/>"
        "<geom type='capsule' size='.02 .1'/></body></worldbody>"
        "<actuator><motor joint='hinge'/></actuator></mujoco>"
    )
    data = mujoco.MjData(model)
    data.ctrl[0] = 0.1
    mujoco.mj_step(model, data)
    assert data.time > 0
    assert np.isfinite(data.qpos).all()
    assert np.isfinite(data.qvel).all()
