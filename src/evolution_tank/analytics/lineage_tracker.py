"""P4-004: Lineage tracking — parent-child relationships across generations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evolution_tank.evolution.engine import GenerationResult
    from evolution_tank.strategy.behavior_tree import BehaviorTree


class LineageTracker:
    """Records strategy lineage: who descended from whom, with fitness."""

    def __init__(self) -> None:
        # List of records: {generation, team_id, lineage_id, parent_ids, fitness}
        self.records: list[dict] = []

    def record(
        self,
        gen_result: GenerationResult,
        populations: dict[int, list[BehaviorTree]],
    ) -> None:
        for team_id, pop in populations.items():
            fitnesses = gen_result.fitnesses.get(team_id, [])
            for i, tree in enumerate(pop):
                fitness = fitnesses[i] if i < len(fitnesses) else 0.0
                self.records.append({
                    "generation": gen_result.generation,
                    "team_id": team_id,
                    "lineage_id": tree.lineage_id,
                    "parent_ids": list(tree.parent_ids),
                    "fitness": fitness,
                })

    def write_json(self, path: Path) -> None:
        if not self.records:
            return
        with open(path, "w") as f:
            json.dump(self.records, f, indent=2)

    def write_jsonl(self, path: Path) -> None:
        """Write as JSON lines — one record per line, easy to stream."""
        if not self.records:
            return
        with open(path, "w") as f:
            for record in self.records:
                f.write(json.dumps(record) + "\n")

    def plot(self, path: Path) -> None:
        """Plot a simplified lineage diagram showing top strategies."""
        if not self.records:
            return

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        team_ids = sorted(set(r["team_id"] for r in self.records))
        generations = sorted(set(r["generation"] for r in self.records))

        if len(generations) < 2:
            return

        fig, axes = plt.subplots(1, len(team_ids), figsize=(8 * len(team_ids), 6), squeeze=False)

        for idx, tid in enumerate(team_ids):
            ax = axes[0][idx]
            team_records = [r for r in self.records if r["team_id"] == tid]

            # Build lookup: lineage_id -> (generation, fitness)
            id_to_info: dict[int, tuple[int, float]] = {}
            for r in team_records:
                id_to_info[r["lineage_id"]] = (r["generation"], r["fitness"])

            # Find the top strategies per generation and trace their lineages
            top_per_gen: dict[int, list[dict]] = {}
            for r in team_records:
                gen = r["generation"]
                if gen not in top_per_gen:
                    top_per_gen[gen] = []
                top_per_gen[gen].append(r)

            # Sort by fitness and take top 5 per generation
            top_n = 5
            for gen in top_per_gen:
                top_per_gen[gen] = sorted(
                    top_per_gen[gen], key=lambda r: r["fitness"], reverse=True,
                )[:top_n]

            # Draw connections from children to parents
            drawn_ids: set[int] = set()
            for gen in sorted(top_per_gen.keys()):
                for r in top_per_gen[gen]:
                    lid = r["lineage_id"]
                    y = r["fitness"]
                    x = r["generation"]

                    # Draw this node
                    ax.scatter(x, y, s=20, color="#4169E1", zorder=3, alpha=0.7)
                    drawn_ids.add(lid)

                    # Draw edges to parents
                    for pid in r["parent_ids"]:
                        if pid in id_to_info:
                            px, py = id_to_info[pid]
                            ax.plot([px, x], [py, y], color="#AAAAAA",
                                    linewidth=0.5, alpha=0.4, zorder=1)

            ax.set_xlabel("Generation")
            ax.set_ylabel("Fitness")
            ax.set_title(f"Team {tid} — Top-{top_n} Lineage")
            ax.grid(True, alpha=0.2)

        fig.suptitle("Strategy Lineage", fontweight="bold")
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
