"""P4-006: Communication analysis — signal usage and correlation with wins."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evolution_tank.evolution.engine import GenerationResult


class CommTracker:
    """Tracks signal usage frequency and win correlation across generations."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, gen_result: GenerationResult) -> None:
        # Aggregate per team across all matches this generation
        team_stats: dict[int, dict] = {}

        for mr in gen_result.match_results:
            for tr in mr.team_results:
                if tr.team_id not in team_stats:
                    team_stats[tr.team_id] = {
                        "total_signals": 0, "matches": 0, "wins": 0,
                    }
                team_stats[tr.team_id]["total_signals"] += tr.total_signals_sent
                team_stats[tr.team_id]["matches"] += 1
                if tr.won:
                    team_stats[tr.team_id]["wins"] += 1

        for team_id, stats in team_stats.items():
            matches = stats["matches"] or 1
            self.records.append({
                "generation": gen_result.generation,
                "team_id": team_id,
                "avg_signals_per_match": stats["total_signals"] / matches,
                "win_rate": stats["wins"] / matches,
            })

    def write_csv(self, path: Path) -> None:
        if not self.records:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["generation", "team_id", "avg_signals_per_match", "win_rate"],
            )
            writer.writeheader()
            writer.writerows(self.records)

    def plot(self, path: Path) -> None:
        if not self.records:
            return

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        team_ids = sorted(set(r["team_id"] for r in self.records))
        colors = ["#4169E1", "#DC143C", "#32CD32", "#FFA500"]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)

        for i, tid in enumerate(team_ids):
            team_recs = [r for r in self.records if r["team_id"] == tid]
            gens = [r["generation"] for r in team_recs]
            signals = [r["avg_signals_per_match"] for r in team_recs]
            win_rates = [r["win_rate"] for r in team_recs]
            color = colors[i % len(colors)]

            ax1.plot(gens, signals, label=f"Team {tid}", color=color, linewidth=1.2)
            ax2.plot(gens, win_rates, label=f"Team {tid}", color=color, linewidth=1.2)

        ax1.set_ylabel("Avg Signals / Match")
        ax1.set_title("Signal Usage Over Generations")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)

        ax2.set_ylabel("Win Rate")
        ax2.set_xlabel("Generation")
        ax2.set_title("Win Rate Over Generations")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
