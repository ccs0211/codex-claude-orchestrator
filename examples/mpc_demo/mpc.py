"""Constrained linear MPC for a 1-D double integrator (position, velocity).

Prediction: X = F x(k) + G U, with X = [x(k+1), ..., x(k+N)].
Cost: sum of predicted tracking errors + input cost + input-increment cost.
Only the first optimal acceleration is applied, then the horizon is replanned.
This educational controller has no terminal invariant set or robustness guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np
from scipy.linalg import block_diag, solve_discrete_are
from scipy.optimize import Bounds, LinearConstraint, minimize


class MPCSolveError(RuntimeError):
    """The optimizer failed or its candidate failed independent feasibility checks."""


@dataclass(frozen=True)
class MPCConfig:
    dt: float = 0.1
    horizon: int = 20
    position_weight: float = 10.0
    velocity_weight: float = 1.0
    input_weight: float = 0.1
    increment_weight: float = 0.05
    max_acceleration: float = 2.0
    max_velocity: float = 0.8
    max_acceleration_change: float = 0.5  # Per sampling interval, NOT per second.
    constraint_tolerance: float = 1e-6

    def __post_init__(self):
        if type(self.horizon) is not int or not 1 <= self.horizon <= 200:
            raise ValueError("horizon must be an integer from 1 to 200")
        for name in ("dt", "position_weight", "velocity_weight", "input_weight",
                     "max_acceleration", "max_velocity", "max_acceleration_change",
                     "constraint_tolerance"):
            value = getattr(self, name)
            if not np.isscalar(value) or not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive scalar")
        if not np.isscalar(self.increment_weight) or not np.isfinite(self.increment_weight) or self.increment_weight < 0:
            raise ValueError("increment_weight must be finite and nonnegative")


@dataclass(frozen=True)
class MPCSolution:
    acceleration: float
    inputs: np.ndarray
    states: np.ndarray
    cost: float
    max_constraint_violation: float
    solve_seconds: float


def prediction_matrices(A, B, horizon):
    """Stack exact discrete-time dynamics; the first block predicts k+1."""
    nx, nu = B.shape
    F = np.zeros((horizon * nx, nx))
    G = np.zeros((horizon * nx, horizon * nu))
    for i in range(horizon):
        F[i * nx:(i + 1) * nx] = np.linalg.matrix_power(A, i + 1)
        for j in range(i + 1):
            G[i * nx:(i + 1) * nx, j * nu:(j + 1) * nu] = np.linalg.matrix_power(A, i - j) @ B
    return F, G


class PositionMPC:
    def __init__(self, config=None):
        self.config = config or MPCConfig()
        c = self.config
        self.A = np.array([[1.0, c.dt], [0.0, 1.0]])
        self.B = np.array([[0.5 * c.dt ** 2], [c.dt]])
        Q = np.diag([c.position_weight, c.velocity_weight])
        R = np.array([[c.input_weight]])
        # DARE is the unconstrained LQR terminal weight; it alone does not prove
        # constrained closed-loop stability, especially with increment penalties.
        self.P = solve_discrete_are(self.A, self.B, Q, R)
        self.Qbar = block_diag(*([Q] * (c.horizon - 1) + [self.P]))
        self.F, self.G = prediction_matrices(self.A, self.B, c.horizon)
        self.D = np.eye(c.horizon) - np.eye(c.horizon, k=-1)
        self.H = 2 * (self.G.T @ self.Qbar @ self.G + c.input_weight * np.eye(c.horizon)
                      + c.increment_weight * self.D.T @ self.D)
        self.H = 0.5 * (self.H + self.H.T)
        self.velocity_G = self.G[1::2]
        self._warm = np.zeros(c.horizon)

    def _linear_terms(self, state, reference_position, previous_acceleration):
        reference = np.tile([reference_position, 0.0], self.config.horizon)
        free = self.F @ state
        offset = np.zeros(self.config.horizon)
        offset[0] = previous_acceleration
        f = 2 * (self.G.T @ self.Qbar @ (free - reference)
                 - self.config.increment_weight * self.D.T @ offset)
        return free, reference, offset, f

    def solve(self, state, reference_position, previous_acceleration=0.0):
        c = self.config
        state = np.asarray(state, dtype=float)
        if state.shape != (2,) or not np.all(np.isfinite(state)):
            raise ValueError("state must be finite [position, velocity]")
        if not np.isscalar(reference_position) or not np.isfinite(reference_position):
            raise ValueError("reference_position must be a finite scalar")
        if (not np.isscalar(previous_acceleration) or not np.isfinite(previous_acceleration)
                or abs(previous_acceleration) > c.max_acceleration):
            raise ValueError("previous_acceleration must be finite and within input limits")

        free, reference, offset, f = self._linear_terms(state, reference_position, previous_acceleration)
        velocity_free = free[1::2]
        matrix = np.vstack([self.velocity_G, self.D])
        lower = np.r_[-c.max_velocity - velocity_free, offset - c.max_acceleration_change]
        upper = np.r_[c.max_velocity - velocity_free, offset + c.max_acceleration_change]
        # At simultaneous active velocity and slew limits, roundoff can turn an
        # exactly feasible constraint intersection into an inconsistent one for
        # SLSQP. Reserve a small fraction of the explicit feasibility tolerance;
        # the physical constraints are independently checked below on the result.
        solver_margin = c.constraint_tolerance * 0.01
        started = time.perf_counter()
        result = minimize(
            fun=lambda u: 0.5 * u @ self.H @ u + f @ u,
            x0=self._warm.copy(), jac=lambda u: self.H @ u + f,
            method="SLSQP", bounds=Bounds(-c.max_acceleration, c.max_acceleration),
            constraints=[LinearConstraint(matrix, lower - solver_margin, upper + solver_margin)],
            options={"maxiter": 300, "ftol": 1e-9, "disp": False},
        )
        duration = time.perf_counter() - started
        if not result.success:
            raise MPCSolveError(f"MPC optimization failed: {result.message}")
        u = np.asarray(result.x, dtype=float)
        if u.shape != (c.horizon,) or not np.all(np.isfinite(u)):
            raise MPCSolveError("Optimizer returned a nonfinite or incorrectly shaped input sequence")
        predicted = (free + self.G @ u).reshape(c.horizon, 2)
        delta = self.D @ u - offset
        violation = max(0.0, float(np.max(np.abs(u) - c.max_acceleration)),
                        float(np.max(np.abs(predicted[:, 1]) - c.max_velocity)),
                        float(np.max(np.abs(delta) - c.max_acceleration_change)))
        error = predicted.ravel() - reference
        cost = float(error @ self.Qbar @ error + c.input_weight * (u @ u)
                     + c.increment_weight * (delta @ delta))
        if not np.all(np.isfinite(predicted)) or not np.isfinite(cost) or violation > c.constraint_tolerance:
            raise MPCSolveError(f"Optimizer candidate rejected: constraint violation {violation:.3g}")
        # Keep the actual optimizer candidate: do not clip a failed solution.
        self._warm = np.r_[u[1:], u[-1]]
        return MPCSolution(float(u[0]), u.copy(), predicted.copy(), cost, violation, duration)


def simulate(config=None, initial_state=(0.0, 0.0), reference_position=1.0, steps=120):
    """Nominal, noise-free, full-state-feedback simulation. No fallback on failure."""
    if type(steps) is not int or steps < 1:
        raise ValueError("steps must be a positive integer")
    controller = PositionMPC(config)
    state = np.asarray(initial_state, dtype=float)
    states, inputs, solutions = [state.copy()], [], []
    previous = 0.0
    for _ in range(steps):
        solution = controller.solve(state, reference_position, previous)
        previous = solution.acceleration
        state = controller.A @ state + controller.B[:, 0] * previous
        states.append(state.copy())
        inputs.append(previous)
        solutions.append(solution)
    return np.asarray(states), np.asarray(inputs), solutions
