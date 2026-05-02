"""P4-005: Win-rate matrices — archetype vs archetype outcomes."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evolution_tank.evolution.engine import GenerationResult
    from evolution_tank.strategy.behavior_tree import BehaviorTree


# ---------------------------------------------------------------------------
# Archetype classification
# ---------------------------------------------------------------------------

# Node types associated with each archetype
_AGGRESSIVE_NODES = {"fire", "aim_at", "move_toward"}
_DEFENSIVE_NODES = {"repair", "seek_cover", "move_away"}
_SCOUT_NODES = {"patrol", "signal", "move_to_signal"}


def _collect_node_types(node) -> list[str]:
    """Recursively collect all node type strings from a tree."""
    result = [node.to_dict().get("type", "unknown")]
    for child in node.get_children():
        result.extend(_collect_node_types(child))
    return result


def classify_archetype(tree: BehaviorTree) -> str:
    """Classify a behavior tree into a strategy archetype."""
    types = _collect_node_types(tree.root)
    total = len(types) or 1

    aggressive = sum(1 for t in types if t in _AGGRESSIVE_NODES) / total
    defensive = sum(1 for t in types if t in _DEFENSIVE_NODES) / total
    scout = sum(1 for t in types if t in _SCOUT_NODES) / total

    # Classify by dominant trait
    scores = {"aggressive": aggressive, "defensive": defensive, "scout": scout}
    best = max(scores, key=scores.get)

    if scores[best] < 0.15:
        return "balanced"
    return best


class WinMatrixTracker:
    """Tracks archetype-vs-archetype win rates across generations."""

    def __init__(self) -> None:
        # (archetype_a, archetype_b) -> {"wins_a": int, "wins_b": int, "draws": int}
        self.matchups: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"wins_a": 0, "wins_b": 0, "draws": 0}
        )

    def record(
        self,
        gen_result: GenerationResult,
        populations: dict[int, list[BehaviorTree]],
    ) -> None:
        team_ids = sorted(populations.keys())
        if len(team_ids) < 2:
            return

        # Classify the best strategy per team this generation
        archetypes: dict[int, str] = {}
        for tid in team_ids:
            fitnesses = gen_result.fitnesses[tid]
            best_idx = fitnesses.index(max(fitnesses))
            archetypes[tid] = classify_archetype(populations[tid][best_idx])

        # Record the generation-level outcome
        key = (archetypes[team_ids[0]], archetypes[team_ids[1]])

        # Count wins from match results
        for mr in gen_result.match_results:
            if mr.winning_team_id == team_ids[0]:
                self.matchups[key]["wins_a"] += 1
            elif mr.winning_team_id == team_ids[1]:
                self.matchups[key]["wins_b"] += 1
            else:
                self.matchups[key]["draws"] += 1

    def write_csv(self, path: Path) -> None:
        if not self.matchups:
            return
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["archetype_a", "archetype_b", "wins_a", "wins_b", "draws", "total"])
            for (a, b), counts in sorted(self.matchups.items()):
                total = counts["wins_a"] + counts["wins_b"] + counts["draws"]
                writer.writerow([a, b, counts["wins_a"], counts["wins_b"], counts["draws"], total])

    def plot_heatmap(self, path: Path) -> None:
        if not self.matchups:
            return

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        # Collect all archetypes
        all_archetypes = sorted(set(
            a for pair in self.matchups for a in pair
        ))
        n = len(all_archetypes)
        if n == 0:
            return

        idx = {a: i for i, a in enumerate(all_archetypes)}
        matrix = np.zeros((n, n))

        for (a, b), counts in self.matchups.items():
            total = counts["wins_a"] + counts["wins_b"] + counts["draws"]
            if total > 0:
                matrix[idx[a]][idx[b]] = counts["wins_a"] / total

        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=1)
        ax.set_xticks(range(n))
        ax.set_xticklabels(all_archetypes, rotation=45, ha="right", fontsize=9)
        ax.set_yticks(range(n))
        ax.set_yticklabels(all_archetypes, fontsize=9)
        ax.set_xlabel("Opponent Archetype")
        ax.set_ylabel("Strategy Archetype")
        ax.set_title("Win Rate Matrix (row vs column)")

        # Annotate cells
        for i in range(n):
            for j in range(n):
                val = matrix[i][j]
                ax.text(j, i, f"{val:.0%}", ha="center", va="center",
                        fontsize=10, color="black" if 0.3 < val < 0.7 else "white")

        fig.colorbar(im, ax=ax, label="Win Rate")
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
