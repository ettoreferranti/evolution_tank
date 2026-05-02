"""P4-001: Fitness tracking — mean/max/min per generation per team."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evolution_tank.evolution.engine import GenerationResult


class FitnessTracker:
    """Accumulates fitness statistics across generations."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, gen_result: GenerationResult) -> None:
        for team_id, fitnesses in gen_result.fitnesses.items():
            if fitnesses:
                self.records.append({
                    "generation": gen_result.generation,
                    "team_id": team_id,
                    "mean": sum(fitnesses) / len(fitnesses),
                    "max": max(fitnesses),
                    "min": min(fitnesses),
                })

    def write_csv(self, path: Path) -> None:
        if not self.records:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["generation", "team_id", "mean", "max", "min"])
            writer.writeheader()
            writer.writerows(self.records)

    def plot(self, path: Path) -> None:
        if not self.records:
            return

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        team_ids = sorted(set(r["team_id"] for r in self.records))
        fig, axes = plt.subplots(1, len(team_ids), figsize=(6 * len(team_ids), 4), squeeze=False)

        for idx, team_id in enumerate(team_ids):
            ax = axes[0][idx]
            team_records = [r for r in self.records if r["team_id"] == team_id]
            gens = [r["generation"] for r in team_records]
            means = [r["mean"] for r in team_records]
            maxes = [r["max"] for r in team_records]
            mins = [r["min"] for r in team_records]

            ax.plot(gens, means, label="mean", color="blue", linewidth=1.5)
            ax.plot(gens, maxes, label="max", color="green", linewidth=0.8, linestyle="--")
            ax.fill_between(gens, mins, maxes, alpha=0.15, color="blue")
            ax.set_title(f"Team {team_id}")
            ax.set_xlabel("Generation")
            ax.set_ylabel("Fitness")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)

        fig.suptitle("Fitness Over Generations", fontweight="bold")
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
