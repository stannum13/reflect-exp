"""Tiny deterministic MuJoCo arm and common bounded PD controller."""

from __future__ import annotations

import numpy as np

from .contracts import ClampReport, ExperimentConfig, frozen_vector


MJCF_BYTES = b'''<mujoco model="reflect_exp01">
  <option timestep="0.002" gravity="0 0 0" integrator="Euler"/>
  <worldbody><body name="base"><joint name="j1" type="hinge" axis="0 0 1" range="-2.7 2.7" damping="0.1"/>
    <geom type="capsule" fromto="0 0 0 .30 0 0" size=".015"/><body pos=".30 0 0"><joint name="j2" type="hinge" axis="0 0 1" range="-2.7 2.7" damping="0.1"/>
    <geom type="capsule" fromto="0 0 0 .25 0 0" size=".015"/><body pos=".25 0 0"><joint name="j3" type="hinge" axis="0 0 1" range="-2.7 2.7" damping="0.1"/>
    <geom type="capsule" fromto="0 0 0 .20 0 0" size=".015"/><site name="eef" pos=".20 0 0" size=".01"/></body></body></body></body></worldbody>
  <actuator><motor joint="j1" ctrlrange="-12 12"/><motor joint="j2" ctrlrange="-12 12"/><motor joint="j3" ctrlrange="-12 12"/></actuator>
</mujoco>'''


def bounded_pd(
    q: np.ndarray,
    dq: np.ndarray,
    requested_q_ref: np.ndarray,
    previous_q_ref: np.ndarray,
    kp: float,
    kd: float,
    config: ExperimentConfig,
) -> tuple[np.ndarray, np.ndarray, ClampReport]:
    values = [np.asarray(x, dtype=np.float64) for x in (q, dq, requested_q_ref, previous_q_ref)]
    if any(x.shape != (3,) or not np.isfinite(x).all() for x in values):
        raise ValueError("bounded_pd inputs must be finite 3-vectors")
    arm = config.arm
    step = config.controller.reference_slew_rad_s * arm.timestep_s
    delta = values[2] - values[3]
    slewed = values[3] + np.clip(delta, -step, step)
    q_ref = np.clip(slewed, arm.joint_min_rad, arm.joint_max_rad)
    raw = kp * (q_ref - values[0]) - kd * values[1]
    torque = np.clip(raw, arm.torque_min_nm, arm.torque_max_nm)
    report = ClampReport(
        reference_clamped=bool(np.any(np.abs(delta) > step)),
        joint_clamped=bool(np.any((slewed < arm.joint_min_rad) | (slewed > arm.joint_max_rad))),
        torque_clamped=bool(np.any((raw < arm.torque_min_nm) | (raw > arm.torque_max_nm))),
    )
    return frozen_vector(q_ref, "q_ref", shape=(3,)), frozen_vector(torque, "torque", shape=(3,)), report


class PlanarArm:
    def __init__(self, config: ExperimentConfig):
        import mujoco

        self._mujoco = mujoco
        self.config = config
        self.model = mujoco.MjModel.from_xml_string(MJCF_BYTES.decode("utf-8"))
        self.data = mujoco.MjData(self.model)

    def reset(self, q: np.ndarray) -> None:
        q = frozen_vector(q, "q", shape=(3,))
        self.mujoco_reset()
        self.data.qpos[:] = q
        self.data.qvel[:] = 0.0
        self._mujoco.mj_forward(self.model, self.data)

    def mujoco_reset(self) -> None:
        self._mujoco.mj_resetData(self.model, self.data)

    def site_xy(self) -> np.ndarray:
        site_id = self._mujoco.mj_name2id(self.model, self._mujoco.mjtObj.mjOBJ_SITE, "eef")
        return frozen_vector(self.data.site_xpos[site_id, :2], "site_xy", shape=(2,))

    def state(self) -> tuple[np.ndarray, np.ndarray]:
        return (
            frozen_vector(self.data.qpos[:3], "q", shape=(3,)),
            frozen_vector(self.data.qvel[:3], "dq", shape=(3,)),
        )

    def step(self, torque: np.ndarray) -> None:
        self.data.ctrl[:] = frozen_vector(torque, "torque", shape=(3,))
        self._mujoco.mj_step(self.model, self.data)
