"""Central analytics collector — orchestrates all trackers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from evolution_tank.analytics.arms_race import ArmsRaceTracker
from evolution_tank.analytics.comm_tracker import CommTracker
from evolution_tank.analytics.diversity_tracker import DiversityTracker
from evolution_tank.analytics.fitness_tracker import FitnessTracker
from evolution_tank.analytics.lineage_tracker import LineageTracker
from evolution_tank.analytics.trait_tracker import TraitTracker
from evolution_tank.analytics.win_matrix import WinMatrixTracker

if TYPE_CHECKING:
    from evolution_tank.config import AnalyticsConfig
    from evolution_tank.evolution.engine import GenerationResult
    from evolution_tank.strategy.behavior_tree import BehaviorTree


class AnalyticsCollector:
    """Accumulates analytics data across generations and writes output."""

    def __init__(self, config: AnalyticsConfig) -> None:
        self._config = config
        self._output_dir = Path(config.output_dir)

        # Always track fitness (cheap)
        self._fitness = FitnessTracker() if config.save_fitness_csv or config.plot_fitness_curves else None
        self._arms_race = ArmsRaceTracker() if config.plot_fitness_curves else None
        self._win_matrix = WinMatrixTracker() if config.save_win_matrix else None
        self._comm = CommTracker() if config.save_fitness_csv else None
        self._diversity = DiversityTracker() if config.save_diversity else None
        self._traits = TraitTracker() if config.save_diversity else None
        self._lineage = LineageTracker() if config.save_lineage else None

    def on_generation(
        self,
        gen_result: GenerationResult,
        populations: dict[int, list[BehaviorTree]],
    ) -> None:
        """Called after each generation. Delegates to sub-trackers."""
        gen = gen_result.generation
        log_every = self._config.log_every_n_generations

        # Fitness and arms race — always record (cheap)
        if self._fitness is not None:
            self._fitness.record(gen_result)
        if self._arms_race is not None:
            self._arms_race.record(gen_result)
        if self._comm is not None:
            self._comm.record(gen_result)
        if self._win_matrix is not None:
            self._win_matrix.record(gen_result, populations)
        if self._lineage is not None:
            self._lineage.record(gen_result, populations)

        # Expensive operations — respect log_every_n_generations
        if gen % log_every == 0:
            if self._diversity is not None:
                self._diversity.record(gen, populations)
            if self._traits is not None:
                self._traits.record(gen, populations)

    def finalize(self) -> None:
        """Write all accumulated data to disk."""
        out = self._output_dir
        out.mkdir(parents=True, exist_ok=True)

        if self._fitness is not None:
            if self._config.save_fitness_csv:
                self._fitness.write_csv(out / "fitness_history.csv")
            if self._config.plot_fitness_curves:
                self._fitness.plot(out / "fitness_curves.png")

        if self._arms_race is not None:
            self._arms_race.write_csv(out / "arms_race.csv")
            if self._config.plot_fitness_curves:
                self._arms_race.plot(out / "arms_race.png")

        if self._win_matrix is not None:
            self._win_matrix.write_csv(out / "win_matrix.csv")
            self._win_matrix.plot_heatmap(out / "win_matrix.png")

        if self._comm is not None:
            self._comm.write_csv(out / "comm_history.csv")
            self._comm.plot(out / "comm_analysis.png")

        if self._diversity is not None:
            self._diversity.write_csv(out / "diversity_history.csv")
            self._diversity.plot(out / "diversity_plot.png")

        if self._traits is not None:
            self._traits.write_csv(out / "trait_history.csv")
            self._traits.write_param_csv(out / "param_history.csv")
            self._traits.write_comp_csv(out / "composition_history.csv")
            self._traits.plot_heatmap(out / "trait_heatmap.png")
            self._traits.plot_composition(out / "composition_plot.png")

        if self._lineage is not None:
            self._lineage.write_jsonl(out / "lineage.jsonl")
            self._lineage.plot(out / "lineage_plot.png")

        print(f"  Analytics saved to {out}/", flush=True)
