import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
from numpy.testing import assert_allclose

from mpc import MPCConfig, MPCSolveError, PositionMPC, prediction_matrices, simulate


class MPCTests(unittest.TestCase):
    def test_predictions_match_independent_rollout(self):
        mpc = PositionMPC(MPCConfig(horizon=5))
        x = np.array([0.3, -0.2])
        u = np.array([0.1, 0.2, -0.1, 0.05, 0.0])
        predicted = (mpc.F @ x + mpc.G @ u).reshape(5, 2)
        actual = []
        for control in u:
            x = mpc.A @ x + mpc.B[:, 0] * control
            actual.append(x.copy())
        assert_allclose(predicted, actual, atol=1e-12)

    def test_cost_gradient_matches_full_cost_finite_difference(self):
        mpc = PositionMPC(MPCConfig(horizon=6))
        free, ref, offset, f = mpc._linear_terms(np.array([0.2, -0.1]), 1.0, 0.3)
        u = np.linspace(-0.2, 0.4, 6)
        def cost(v):
            e, d = free + mpc.G @ v - ref, mpc.D @ v - offset
            return e @ mpc.Qbar @ e + mpc.config.input_weight * (v @ v) + mpc.config.increment_weight * (d @ d)
        eps = 1e-6
        numerical = np.array([(cost(u + eps * e) - cost(u - eps * e)) / (2 * eps) for e in np.eye(6)])
        assert_allclose(mpc.H @ u + f, numerical, rtol=1e-6, atol=1e-6)

    def test_tracking_and_realized_constraints_in_both_directions(self):
        c = MPCConfig()
        for target in (1.0, -1.0):
            with self.subTest(target=target):
                states, inputs, solutions = simulate(c, reference_position=target, steps=100)
                self.assertLess(abs(states[-1, 0] - target), 0.01)
                self.assertLess(abs(states[-1, 1]), 0.01)
                self.assertLessEqual(np.max(np.abs(inputs)), c.max_acceleration + 1e-6)
                self.assertLessEqual(np.max(np.abs(states[:, 1])), c.max_velocity + 1e-6)
                self.assertLessEqual(np.max(np.abs(np.diff(np.r_[0.0, inputs]))), c.max_acceleration_change + 1e-6)
                for i, solution in enumerate(solutions):
                    assert_allclose(solution.states[0], states[i + 1], atol=1e-12)

    def test_equilibrium_has_zero_control_and_zero_cost(self):
        result = PositionMPC().solve([1.0, 0.0], 1.0)
        assert_allclose(result.inputs, 0.0, atol=1e-8)
        self.assertLess(abs(result.cost), 1e-10)

    def test_first_increment_uses_previous_input(self):
        c = MPCConfig()
        solution = PositionMPC(c).solve([0.0, 0.0], 1.0, previous_acceleration=-1.0)
        self.assertLessEqual(abs(solution.inputs[0] + 1.0), c.max_acceleration_change + 1e-6)

    def test_infeasible_velocity_raises(self):
        with self.assertRaises(MPCSolveError):
            PositionMPC().solve([0.0, 2.0], 1.0)

    def test_solver_failure_is_not_silently_replaced(self):
        with patch("mpc.minimize", return_value=SimpleNamespace(success=False, message="forced failure")):
            with self.assertRaisesRegex(MPCSolveError, "forced failure"):
                PositionMPC().solve([0, 0], 1)

    def test_success_flag_does_not_override_nonfinite_or_violating_solution(self):
        for values in (np.full(20, np.nan), np.full(20, 99.0), np.zeros(19)):
            with self.subTest(values=values[:2]):
                with patch("mpc.minimize", return_value=SimpleNamespace(success=True, x=values)):
                    with self.assertRaises(MPCSolveError):
                        PositionMPC().solve([0, 0], 1)

    def test_invalid_inputs_are_rejected(self):
        mpc = PositionMPC()
        for state in ([0], [[0, 0]], [np.nan, 0], [0, np.inf]):
            with self.subTest(state=state), self.assertRaises(ValueError):
                mpc.solve(state, 1)
        for target in (np.nan, np.inf, [1]):
            with self.subTest(target=target), self.assertRaises(ValueError):
                mpc.solve([0, 0], target)
        for previous in (np.nan, 3, [0]):
            with self.subTest(previous=previous), self.assertRaises(ValueError):
                mpc.solve([0, 0], 1, previous)

    def test_invalid_configuration_is_rejected(self):
        for changes in ({"horizon": 0}, {"horizon": True}, {"dt": 0}, {"input_weight": -1},
                        {"max_velocity": np.inf}, {"increment_weight": -1}, {"max_acceleration_change": np.nan}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                MPCConfig(**changes)

    def test_one_step_horizon_and_finite_solution(self):
        solution = PositionMPC(MPCConfig(horizon=1)).solve([0, 0], 1)
        self.assertEqual(solution.states.shape, (1, 2))
        self.assertTrue(np.isfinite(solution.cost))


if __name__ == "__main__":
    unittest.main(verbosity=2)
