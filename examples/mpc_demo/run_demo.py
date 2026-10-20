"""Run the MPC example, save raw results and a figure, exit nonzero on failure."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from mpc import MPCConfig, simulate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "artifacts")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = MPCConfig()
    reference = 1.0
    states, inputs, solutions = simulate(config, reference_position=reference)
    metrics = {
        "config": asdict(config), "steps": len(inputs), "reference_position": reference,
        "final_position": float(states[-1, 0]), "final_velocity": float(states[-1, 1]),
        "final_position_error": float(abs(states[-1, 0] - reference)),
        "max_abs_acceleration": float(np.max(np.abs(inputs))),
        "max_abs_velocity": float(np.max(np.abs(states[:, 1]))),
        "max_abs_acceleration_change": float(np.max(np.abs(np.diff(np.r_[0.0, inputs])))),
        "max_predicted_constraint_violation": max(s.max_constraint_violation for s in solutions),
        "max_one_step_prediction_error": float(max(np.max(np.abs(s.states[0] - states[k + 1]))
                                                   for k, s in enumerate(solutions))),
        "median_solve_ms": float(np.median([s.solve_seconds for s in solutions]) * 1000),
        "max_solve_ms": float(max(s.solve_seconds for s in solutions) * 1000),
    }
    if metrics["final_position_error"] > 0.01 or abs(metrics["final_velocity"]) > 0.01:
        raise RuntimeError("Tracking acceptance check failed")
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    time = np.arange(len(states)) * config.dt
    np.savetxt(args.output_dir / "trajectory.csv", np.c_[time, states, np.r_[inputs, np.nan]], delimiter=",",
               header="time_s,position_m,velocity_m_s,acceleration_applied_m_s2", comments="")
    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True, layout="constrained")
    axes[0].plot(time, states[:, 0], label="Position")
    axes[0].axhline(reference, color="0.45", ls="--", label="Reference")
    axes[0].set_ylabel("Position (m)")
    axes[0].legend(loc="lower right")
    axes[1].plot(time, states[:, 1], color="#1c8b68")
    axes[1].axhline(config.max_velocity, color="#b85643", ls="--")
    axes[1].axhline(-config.max_velocity, color="#b85643", ls="--")
    axes[1].set_ylabel("Velocity (m/s)")
    axes[2].step(time[:-1], inputs, where="post", color="#8054a0")
    axes[2].axhline(config.max_acceleration, color="#b85643", ls="--")
    axes[2].axhline(-config.max_acceleration, color="#b85643", ls="--")
    axes[2].set_ylabel("Acceleration (m/s²)")
    axes[2].set_xlabel("Time (s)")
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.suptitle("Constrained MPC: 1-D position tracking")
    fig.savefig(args.output_dir / "mpc_tracking.png", dpi=160)
    plt.close(fig)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
