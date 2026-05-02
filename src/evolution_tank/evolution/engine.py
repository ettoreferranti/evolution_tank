"""Evolution engine — orchestrates the full evolutionary loop."""

from __future__ import annotations

import multiprocessing
import os
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from evolution_tank.evolution.fitness import compute_fitness
from evolution_tank.evolution.selection import select_next_generation
from evolution_tank.simulation.arena import Vector2, load_preset
from evolution_tank.simulation.match import MatchResult, run_match
from evolution_tank.strategy.behavior_tree import BehaviorTree
from evolution_tank.strategy.random_tree import generate_random_tree
from evolution_tank.strategy.serialization import deserialize_tree, serialize_tree
from evolution_tank.tanks.tank import Tank, TankType

if TYPE_CHECKING:
    from evolution_tank.config import Config


# ---------------------------------------------------------------------------
# Generation data
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    """Results for one generation of evolution."""
    generation: int
    fitnesses: dict[int, list[float]]  # team_id → list of fitness scores
    best_fitness: dict[int, float]     # team_id → best fitness
    mean_fitness: dict[int, float]     # team_id → mean fitness
    match_results: list[MatchResult]


# Callback type for per-generation hooks (logging, visualization, etc.)
GenerationCallback = Callable[[GenerationResult, dict[int, list[BehaviorTree]]], None]


# ---------------------------------------------------------------------------
# Standalone match runner (top-level function for multiprocessing)
# ---------------------------------------------------------------------------

def _run_match_worker(args: tuple) -> MatchResult:
    """Run a single match in a worker process.

    Takes a tuple of serializable arguments so it can be dispatched
    via multiprocessing.Pool.
    """
    config, arena, tree_a_data, tree_b_data, team_a_id, team_b_id, seed = args

    strategy_a = deserialize_tree(tree_a_data)
    strategy_b = deserialize_tree(tree_b_data)
    strategy_a.reset()
    strategy_b.reset()

    rng = random.Random(seed)
    team_size = config.match.team_size

    spawn = arena.compute_spawn_positions(2, team_size, config.match.spawn, rng)
    center = Vector2(arena.width / 2, arena.height / 2)

    tanks: list[Tank] = []
    strategies: dict[int, any] = {}
    tank_id = 0

    for team_idx, (team_id, strategy) in enumerate([
        (team_a_id, strategy_a),
        (team_b_id, strategy_b),
    ]):
        if strategy.composition is not None:
            comp = strategy.composition
        elif config.evolution.composition.enabled:
            comp = config.evolution.composition.fixed_composition
        else:
            comp = {"medium": team_size}

        type_sequence = EvolutionEngine._composition_to_sequence(comp, team_size)
        strategy_fn = strategy.to_strategy_fn(arena)

        for i in range(team_size):
            pos = spawn[team_idx][i]
            heading = (center - pos).angle()
            tt = type_sequence[i % len(type_sequence)]
            t = Tank(
                id=tank_id, team_id=team_id, tank_type=tt,
                type_config=config.tank_types[tt.value],
                position=pos, heading=heading, turret_angle=heading,
            )
            tanks.append(t)
            strategies[tank_id] = strategy_fn
            tank_id += 1

    return run_match(config, arena, tanks, strategies)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EvolutionEngine:
    """Runs the full evolution loop.

    Maintains two independent populations (one per team). Each generation:
    1. Pair strategies from opposing populations.
    2. Run matches to evaluate fitness.
    3. Select, crossover, and mutate to produce the next generation.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        # Use all available cores, leaving one free for the OS / UI
        self._num_workers = max(1, os.cpu_count() - 1)

    def initialize_populations(self, rng: random.Random) -> dict[int, list[BehaviorTree]]:
        """Create generation 0 populations for each team."""
        pop_size = self.config.evolution.population_size
        populations: dict[int, list[BehaviorTree]] = {}

        comp_enabled = self.config.evolution.composition.enabled
        team_size = self.config.match.team_size

        for team_id in range(self.config.match.team_count):
            pop: list[BehaviorTree] = []
            for _ in range(pop_size):
                tree = generate_random_tree(
                    rng, max_depth=self.config.evolution.max_tree_depth,
                    team_size=team_size,
                    composition_enabled=comp_enabled,
                )
                pop.append(tree)
            populations[team_id] = pop

        return populations

    def run_generation(
        self,
        populations: dict[int, list[BehaviorTree]],
        generation: int,
        rng: random.Random,
        match_callback: Callable[[int, int], None] | None = None,
    ) -> GenerationResult:
        """Evaluate all strategies by running matches.

        Each strategy plays matches_per_strategy opponents from the
        opposing population. Matches run in parallel across CPU cores.
        """
        config = self.config
        team_ids = sorted(populations.keys())
        matches_per = config.evolution.matches_per_strategy

        # Get arena for this generation (rotate presets if configured)
        arena = self._get_arena(generation)

        # Pre-serialize all trees (once) for worker dispatch
        serialized: dict[int, list[dict]] = {
            tid: [serialize_tree(t) for t in populations[tid]]
            for tid in team_ids
        }

        # Build the list of all match tasks
        # Each task: (team_id, strat_idx, opp_team_id, opp_idx, seed)
        match_tasks: list[tuple] = []
        task_keys: list[tuple[int, int]] = []  # (team_id, strat_idx) for each task

        for team_id in team_ids:
            opp_team_id = (team_id + 1) % len(team_ids)

            for strat_idx in range(len(populations[team_id])):
                opp_indices = [
                    rng.randrange(len(populations[opp_team_id]))
                    for _ in range(matches_per)
                ]

                for opp_idx in opp_indices:
                    # Each match gets a unique seed derived from the main rng
                    match_seed = rng.randint(0, 2**31 - 1)
                    match_tasks.append((
                        config, arena,
                        serialized[team_id][strat_idx],
                        serialized[opp_team_id][opp_idx],
                        team_id, opp_team_id,
                        match_seed,
                    ))
                    task_keys.append((team_id, strat_idx))

        total_matches = len(match_tasks)

        # Run matches in parallel
        strategy_results: dict[int, dict[int, list[MatchResult]]] = {
            tid: {i: [] for i in range(len(populations[tid]))}
            for tid in team_ids
        }
        all_match_results: list[MatchResult] = []

        pool = multiprocessing.Pool(self._num_workers)
        try:
            for i, result in enumerate(pool.imap(_run_match_worker, match_tasks)):
                team_id, strat_idx = task_keys[i]
                strategy_results[team_id][strat_idx].append(result)
                all_match_results.append(result)
                if match_callback is not None:
                    match_callback(i + 1, total_matches)
        except KeyboardInterrupt:
            pool.terminate()
            pool.join()
            raise
        else:
            pool.close()
            pool.join()

        # Compute fitness for each strategy
        fitnesses: dict[int, list[float]] = {}
        for team_id in team_ids:
            team_fitnesses: list[float] = []
            for strat_idx in range(len(populations[team_id])):
                results = strategy_results[team_id][strat_idx]
                if results:
                    total = 0.0
                    for mr in results:
                        for tr in mr.team_results:
                            if tr.team_id == team_id:
                                total += compute_fitness(tr, mr, config.fitness)
                                break
                    avg = total / len(results)
                else:
                    avg = 0.0
                team_fitnesses.append(avg)
            fitnesses[team_id] = team_fitnesses

        # Compute stats
        best_fitness = {}
        mean_fitness = {}
        for team_id in team_ids:
            f = fitnesses[team_id]
            best_fitness[team_id] = max(f) if f else 0.0
            mean_fitness[team_id] = sum(f) / len(f) if f else 0.0

        return GenerationResult(
            generation=generation,
            fitnesses=fitnesses,
            best_fitness=best_fitness,
            mean_fitness=mean_fitness,
            match_results=all_match_results,
        )

    def evolve(
        self,
        populations: dict[int, list[BehaviorTree]],
        fitnesses: dict[int, list[float]],
        rng: random.Random,
    ) -> dict[int, list[BehaviorTree]]:
        """Produce the next generation via selection, crossover, mutation."""
        new_populations: dict[int, list[BehaviorTree]] = {}
        for team_id, pop in populations.items():
            new_populations[team_id] = select_next_generation(
                pop, fitnesses[team_id], self.config.evolution, rng,
            )
        return new_populations

    def run(
        self,
        callback: GenerationCallback | None = None,
        rng: random.Random | None = None,
    ) -> dict[int, list[BehaviorTree]]:
        """Run the full evolution loop.

        Args:
            callback: Called after each generation with results and populations.
            rng: Seeded RNG. If None, uses config seed.

        Returns:
            Final populations after all generations.
        """
        if rng is None:
            rng = random.Random(self.config.seed)

        populations = self.initialize_populations(rng)

        for gen in range(self.config.evolution.generations):
            gen_result = self.run_generation(populations, gen, rng)

            if callback is not None:
                callback(gen_result, populations)

            # Evolve to next generation (skip on last generation)
            if gen < self.config.evolution.generations - 1:
                populations = self.evolve(
                    populations, gen_result.fitnesses, rng,
                )

        return populations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_arena(self, generation: int):
        """Get the arena for a given generation, rotating presets if configured."""
        config = self.config
        if config.arena.rotate_presets and config.arena.preset_rotation:
            presets = config.arena.preset_rotation
            preset_name = presets[generation % len(presets)]
        else:
            preset_name = config.arena.preset
        return load_preset(preset_name)

    def _run_single_match(
        self,
        arena,
        strategy_a: BehaviorTree,
        strategy_b: BehaviorTree,
        team_a_id: int,
        team_b_id: int,
        rng: random.Random,
    ) -> MatchResult:
        """Run a single match between two strategies (used for replays)."""
        config = self.config
        team_size = config.match.team_size

        strategy_a.reset()
        strategy_b.reset()

        spawn = arena.compute_spawn_positions(2, team_size, config.match.spawn, rng)
        center = Vector2(arena.width / 2, arena.height / 2)

        tanks: list[Tank] = []
        strategies: dict[int, any] = {}
        tank_id = 0

        for team_idx, (team_id, strategy) in enumerate([
            (team_a_id, strategy_a),
            (team_b_id, strategy_b),
        ]):
            if strategy.composition is not None:
                comp = strategy.composition
            elif config.evolution.composition.enabled:
                comp = config.evolution.composition.fixed_composition
            else:
                comp = {"medium": team_size}

            type_sequence = self._composition_to_sequence(comp, team_size)
            strategy_fn = strategy.to_strategy_fn(arena)

            for i in range(team_size):
                pos = spawn[team_idx][i]
                heading = (center - pos).angle()
                tt = type_sequence[i % len(type_sequence)]
                t = Tank(
                    id=tank_id, team_id=team_id, tank_type=tt,
                    type_config=config.tank_types[tt.value],
                    position=pos, heading=heading, turret_angle=heading,
                )
                tanks.append(t)
                strategies[tank_id] = strategy_fn
                tank_id += 1

        return run_match(config, arena, tanks, strategies)

    @staticmethod
    def _composition_to_sequence(comp: dict[str, int], team_size: int) -> list[TankType]:
        """Convert a composition dict to a repeating sequence of TankTypes."""
        sequence: list[TankType] = []
        type_map = {"light": TankType.LIGHT, "medium": TankType.MEDIUM, "heavy": TankType.HEAVY}
        for type_name, count in comp.items():
            if type_name in type_map:
                sequence.extend([type_map[type_name]] * count)
        # If composition doesn't fill team_size, pad with medium
        while len(sequence) < team_size:
            sequence.append(TankType.MEDIUM)
        return sequence[:team_size]
