"""P4-002: Strategy diversity — tree edit distance distribution over generations."""

from __future__ import annotations

import csv
import hashlib
import json
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING

from evolution_tank.strategy.serialization import serialize_tree

if TYPE_CHECKING:
    from evolution_tank.strategy.behavior_tree import BehaviorTree


# ---------------------------------------------------------------------------
# Tree distance
# ---------------------------------------------------------------------------

def _structure_hash(node_dict: dict) -> str:
    """Hash a serialized tree ignoring parameter values — structure only."""
    stripped = _strip_params(node_dict)
    raw = json.dumps(stripped, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


def _strip_params(node_dict: dict) -> dict:
    """Recursively remove 'params' from a serialized tree dict."""
    result = {"type": node_dict.get("type", "?")}
    if "children" in node_dict:
        result["children"] = [_strip_params(c) for c in node_dict["children"]]
    return result


def tree_edit_distance(dict_a: dict, dict_b: dict) -> int:
    """Simplified tree edit distance on serialized dicts.

    Compares node types position-by-position. Cost = 1 per type mismatch,
    then recursively compare children aligned by index.
    """
    cost = 0 if dict_a.get("type") == dict_b.get("type") else 1

    children_a = dict_a.get("children", [])
    children_b = dict_b.get("children", [])

    # Match children by position, count extras
    for i in range(max(len(children_a), len(children_b))):
        if i < len(children_a) and i < len(children_b):
            cost += tree_edit_distance(children_a[i], children_b[i])
        elif i < len(children_a):
            cost += _count_nodes(children_a[i])
        else:
            cost += _count_nodes(children_b[i])

    return cost


def _count_nodes(node_dict: dict) -> int:
    """Count total nodes in a serialized tree."""
    count = 1
    for child in node_dict.get("children", []):
        count += _count_nodes(child)
    return count


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class DiversityTracker:
    """Tracks structural diversity of populations over generations."""

    def __init__(self, sample_size: int = 20) -> None:
        self.records: list[dict] = []
        self._sample_size = sample_size

    def record(
        self,
        generation: int,
        populations: dict[int, list[BehaviorTree]],
        rng=None,
    ) -> None:
        import random as _random
        rng = rng or _random

        for team_id, pop in populations.items():
            serialized = [serialize_tree(t) for t in pop]

            # Unique structures
            hashes = set(_structure_hash(s) for s in serialized)

            # Subsample for pairwise distance
            if len(serialized) <= self._sample_size:
                sample = serialized
            else:
                sample = rng.sample(serialized, self._sample_size)

            if len(sample) >= 2:
                distances = [
                    tree_edit_distance(a, b)
                    for a, b in combinations(sample, 2)
                ]
                mean_dist = sum(distances) / len(distances)
            else:
                mean_dist = 0.0

            self.records.append({
                "generation": generation,
                "team_id": team_id,
                "mean_edit_distance": mean_dist,
                "unique_structures": len(hashes),
                "population_size": len(pop),
            })

    def write_csv(self, path: Path) -> None:
        if not self.records:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["generation", "team_id", "mean_edit_distance",
                            "unique_structures", "population_size"],
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
            recs = [r for r in self.records if r["team_id"] == tid]
            gens = [r["generation"] for r in recs]
            dists = [r["mean_edit_distance"] for r in recs]
            unique = [r["unique_structures"] for r in recs]
            color = colors[i % len(colors)]

            ax1.plot(gens, dists, label=f"Team {tid}", color=color, linewidth=1.2)
            ax2.plot(gens, unique, label=f"Team {tid}", color=color, linewidth=1.2)

        ax1.set_ylabel("Mean Edit Distance")
        ax1.set_title("Strategy Diversity Over Generations")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)

        ax2.set_ylabel("Unique Structures")
        ax2.set_xlabel("Generation")
        ax2.set_title("Structural Variety")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
