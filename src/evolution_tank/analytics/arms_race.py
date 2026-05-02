"""P4-007: Arms race dynamics — fitness oscillation between co-evolving teams."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evolution_tank.evolution.engine import GenerationResult


class ArmsRaceTracker:
    """Tracks Red Queen dynamics between co-evolving teams."""

    def __init__(self) -> None:
        self.records: list[dict] = []  # {generation, team_means..., delta}

    def record(self, gen_result: GenerationResult) -> None:
        team_ids = sorted(gen_result.mean_fitness.keys())
        row: dict = {"generation": gen_result.generation}
        for tid in team_ids:
            row[f"team{tid}_mean"] = gen_result.mean_fitness[tid]
        if len(team_ids) >= 2:
            row["delta"] = gen_result.mean_fitness[team_ids[0]] - gen_result.mean_fitness[team_ids[1]]
        self.records.append(row)

    def write_csv(self, path: Path) -> None:
        if not self.records:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.records[0].keys()))
            writer.writeheader()
            writer.writerows(self.records)

    def plot(self, path: Path) -> None:
        if not self.records:
            return

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        gens = [r["generation"] for r in self.records]

        # Find team columns
        team_cols = [k for k in self.records[0] if k.startswith("team") and k.endswith("_mean")]
        has_delta = "delta" in self.records[0]

        nrows = 2 if has_delta else 1
        fig, axes = plt.subplots(nrows, 1, figsize=(8, 4 * nrows), squeeze=False)

        # Panel 1: overlaid team fitness
        ax1 = axes[0][0]
        colors = ["#4169E1", "#DC143C", "#32CD32", "#FFA500"]
        for i, col in enumerate(team_cols):
            vals = [r[col] for r in self.records]
            label = col.replace("_mean", "").replace("team", "Team ")
            ax1.plot(gens, vals, label=label, color=colors[i % len(colors)], linewidth=1.5)
        ax1.set_ylabel("Mean Fitness")
        ax1.set_title("Co-evolutionary Fitness")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)

        # Panel 2: delta
        if has_delta:
            ax2 = axes[1][0]
            deltas = [r["delta"] for r in self.records]
            ax2.plot(gens, deltas, color="#333333", linewidth=1)
            ax2.axhline(0, color="gray", linestyle="--", linewidth=0.5)
            ax2.fill_between(gens, 0, deltas,
                             where=[d > 0 for d in deltas], alpha=0.3, color=colors[0], label="Team 0 leads")
            ax2.fill_between(gens, 0, deltas,
                             where=[d < 0 for d in deltas], alpha=0.3, color=colors[1], label="Team 1 leads")
            ax2.set_ylabel("Fitness Delta (T0 - T1)")
            ax2.set_xlabel("Generation")
            ax2.set_title("Arms Race Oscillation")
            ax2.legend(fontsize=8)
            ax2.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
