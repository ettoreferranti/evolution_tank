"""P4-003: Dominant trait tracking — node type frequencies and parameter convergence."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evolution_tank.strategy.behavior_tree import BehaviorTree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_all_nodes(node) -> list:
    """Recursively collect all nodes from a tree."""
    result = [node]
    for child in node.get_children():
        result.extend(_collect_all_nodes(child))
    return result


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class TraitTracker:
    """Tracks node type frequencies and numeric parameter statistics."""

    def __init__(self) -> None:
        self.type_records: list[dict] = []   # {gen, team_id, node_type, frequency}
        self.param_records: list[dict] = []  # {gen, team_id, param_name, mean, std}
        self.comp_records: list[dict] = []   # {gen, team_id, light, medium, heavy}

    def record(
        self,
        generation: int,
        populations: dict[int, list[BehaviorTree]],
    ) -> None:
        for team_id, pop in populations.items():
            self._record_node_types(generation, team_id, pop)
            self._record_params(generation, team_id, pop)
            self._record_compositions(generation, team_id, pop)

    def _record_node_types(
        self, generation: int, team_id: int, pop: list[BehaviorTree],
    ) -> None:
        type_counts: Counter = Counter()
        total_nodes = 0

        for tree in pop:
            nodes = _collect_all_nodes(tree.root)
            for node in nodes:
                node_type = node.to_dict().get("type", "unknown")
                type_counts[node_type] += 1
                total_nodes += 1

        for node_type, count in type_counts.items():
            self.type_records.append({
                "generation": generation,
                "team_id": team_id,
                "node_type": node_type,
                "frequency": count / total_nodes if total_nodes > 0 else 0.0,
                "count": count,
            })

    def _record_params(
        self, generation: int, team_id: int, pop: list[BehaviorTree],
    ) -> None:
        # Collect all numeric params across population
        param_values: dict[str, list[float]] = defaultdict(list)

        for tree in pop:
            nodes = _collect_all_nodes(tree.root)
            for node in nodes:
                node_type = node.to_dict().get("type", "unknown")
                params = node.get_params()
                for pname, pval in params.items():
                    if isinstance(pval, (int, float)):
                        key = f"{node_type}.{pname}"
                        param_values[key].append(float(pval))

        for pname, values in param_values.items():
            n = len(values)
            mean = sum(values) / n
            variance = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0.0
            std = variance ** 0.5
            self.param_records.append({
                "generation": generation,
                "team_id": team_id,
                "param_name": pname,
                "mean": mean,
                "std": std,
                "count": n,
            })

    def _record_compositions(
        self, generation: int, team_id: int, pop: list[BehaviorTree],
    ) -> None:
        light_total = 0
        medium_total = 0
        heavy_total = 0
        count = 0

        for tree in pop:
            if tree.composition is not None:
                light_total += tree.composition.get("light", 0)
                medium_total += tree.composition.get("medium", 0)
                heavy_total += tree.composition.get("heavy", 0)
                count += 1

        if count > 0:
            self.comp_records.append({
                "generation": generation,
                "team_id": team_id,
                "avg_light": light_total / count,
                "avg_medium": medium_total / count,
                "avg_heavy": heavy_total / count,
            })

    def write_csv(self, path: Path) -> None:
        if not self.type_records:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["generation", "team_id", "node_type", "frequency", "count"],
            )
            writer.writeheader()
            writer.writerows(self.type_records)

    def write_param_csv(self, path: Path) -> None:
        if not self.param_records:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["generation", "team_id", "param_name", "mean", "std", "count"],
            )
            writer.writeheader()
            writer.writerows(self.param_records)

    def write_comp_csv(self, path: Path) -> None:
        if not self.comp_records:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["generation", "team_id", "avg_light", "avg_medium", "avg_heavy"],
            )
            writer.writeheader()
            writer.writerows(self.comp_records)

    def plot_heatmap(self, path: Path) -> None:
        if not self.type_records:
            return

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        team_ids = sorted(set(r["team_id"] for r in self.type_records))
        all_types = sorted(set(r["node_type"] for r in self.type_records))
        gens = sorted(set(r["generation"] for r in self.type_records))

        if not all_types or not gens:
            return

        fig, axes = plt.subplots(1, len(team_ids), figsize=(6 * len(team_ids), 5), squeeze=False)

        for idx, tid in enumerate(team_ids):
            ax = axes[0][idx]
            matrix = np.zeros((len(all_types), len(gens)))
            gen_idx = {g: i for i, g in enumerate(gens)}
            type_idx = {t: i for i, t in enumerate(all_types)}

            for r in self.type_records:
                if r["team_id"] == tid and r["generation"] in gen_idx:
                    matrix[type_idx[r["node_type"]]][gen_idx[r["generation"]]] = r["frequency"]

            im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", interpolation="nearest")
            ax.set_yticks(range(len(all_types)))
            ax.set_yticklabels(all_types, fontsize=7)
            ax.set_xlabel("Generation")
            ax.set_title(f"Team {tid} — Node Type Frequency")

            # Show generation labels if few enough
            if len(gens) <= 20:
                ax.set_xticks(range(len(gens)))
                ax.set_xticklabels(gens, fontsize=7)

            fig.colorbar(im, ax=ax, shrink=0.8)

        fig.suptitle("Trait Distribution Over Generations", fontweight="bold")
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)

    def plot_composition(self, path: Path) -> None:
        if not self.comp_records:
            return

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        team_ids = sorted(set(r["team_id"] for r in self.comp_records))

        fig, axes = plt.subplots(1, len(team_ids), figsize=(6 * len(team_ids), 4), squeeze=False)

        for idx, tid in enumerate(team_ids):
            ax = axes[0][idx]
            recs = [r for r in self.comp_records if r["team_id"] == tid]
            gens = [r["generation"] for r in recs]

            ax.stackplot(
                gens,
                [r["avg_light"] for r in recs],
                [r["avg_medium"] for r in recs],
                [r["avg_heavy"] for r in recs],
                labels=["Light", "Medium", "Heavy"],
                colors=["#90EE90", "#4682B4", "#8B0000"],
                alpha=0.8,
            )
            ax.set_title(f"Team {tid} — Avg Composition")
            ax.set_xlabel("Generation")
            ax.set_ylabel("Avg Count")
            ax.legend(fontsize=8, loc="upper right")
            ax.grid(True, alpha=0.3)

        fig.suptitle("Team Composition Over Generations", fontweight="bold")
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
