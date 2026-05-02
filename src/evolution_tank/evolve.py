"""Evolve — run the evolution loop with optional Pygame visualization."""

from __future__ import annotations

import multiprocessing
import random
import time

from evolution_tank.analytics import AnalyticsCollector
from evolution_tank.config import Config
from evolution_tank.evolution.engine import EvolutionEngine, GenerationResult
from evolution_tank.strategy.behavior_tree import BehaviorTree
from evolution_tank.strategy.serialization import serialize_tree


def _format_composition(comp: dict[str, int] | None) -> str:
    """Format a composition dict as a compact string like '2L/2M/1H'."""
    if comp is None:
        return "default"
    return f"{comp.get('light', 0)}L/{comp.get('medium', 0)}M/{comp.get('heavy', 0)}H"


def _print_generation(gen_result: GenerationResult,
                      populations: dict[int, list[BehaviorTree]]) -> None:
    """Print a one-line summary for a generation."""
    parts = [f"Gen {gen_result.generation:3d}"]
    for team_id in sorted(gen_result.fitnesses.keys()):
        best_f = gen_result.best_fitness[team_id]
        mean_f = gen_result.mean_fitness[team_id]

        # Find best strategy to show its composition
        fitnesses = gen_result.fitnesses[team_id]
        best_idx = fitnesses.index(max(fitnesses))
        best_tree = populations[team_id][best_idx]
        comp_str = _format_composition(best_tree.composition)

        parts.append(f"T{team_id}: best={best_f:6.1f} mean={mean_f:5.1f} comp={comp_str}")

    print(" | ".join(parts), flush=True)


def _replay_in_subprocess(
    config: Config,
    tree_data_a: dict,
    tree_data_b: dict,
    generation: int,
    arena_preset: str,
) -> None:
    """Run a replay entirely inside a child process (owns all of Pygame).

    This function is the target for multiprocessing.Process. When it returns,
    the OS tears down the process and its window — no ghost windows.
    """
    import pygame  # noqa: import only in the child process

    from evolution_tank.evolution.engine import EvolutionEngine
    from evolution_tank.simulation.arena import Vector2, load_preset
    from evolution_tank.simulation.match import MatchState, run_match
    from evolution_tank.strategy.serialization import deserialize_tree
    from evolution_tank.tanks.tank import Tank
    from evolution_tank.visualization.renderer import BattleRenderer

    arena = load_preset(arena_preset)
    strategy_a = deserialize_tree(tree_data_a)
    strategy_b = deserialize_tree(tree_data_b)
    strategy_a.reset()
    strategy_b.reset()

    team_size = config.match.team_size
    rng = random.Random(config.seed + generation)
    spawn = arena.compute_spawn_positions(2, team_size, config.match.spawn, rng)
    center = Vector2(arena.width / 2, arena.height / 2)

    tanks: list[Tank] = []
    strategies: dict[int, any] = {}
    tank_id = 0

    for team_idx, (team_id, strategy) in enumerate([
        (0, strategy_a),
        (1, strategy_b),
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

    renderer = BattleRenderer(config, arena)

    running = True
    ticks_to_skip = 0

    def tick_callback(state: MatchState, arena_ref) -> None:
        nonlocal running, ticks_to_skip
        if not running:
            return

        if renderer.speed_multiplier > 1:
            ticks_to_skip += 1
            if ticks_to_skip < renderer.speed_multiplier:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    if event.type == pygame.KEYDOWN:
                        renderer._handle_key(event)
                return
            ticks_to_skip = 0

        while renderer.paused and running:
            if not renderer.render_tick(state, arena_ref):
                running = False
                return

        if not renderer.render_tick(state, arena_ref):
            running = False

    result = run_match(config, arena, tanks, strategies, tick_callback)

    if running:
        renderer.show_result(result)
        winner = f"Team {result.winning_team_id}" if result.winning_team_id is not None else "Draw"
        print(f"  Result: {winner}, {result.total_ticks} ticks")
        for tr in result.team_results:
            ff = f" ff={tr.total_friendly_damage:.0f}" if tr.total_friendly_damage > 0 else ""
            print(f"    T{tr.team_id}: alive={tr.tanks_alive} dmg={tr.total_damage_dealt:.0f}{ff} "
                  f"kills={tr.total_kills} shots={tr.total_shots_fired}/{tr.total_shots_hit}")
        print(flush=True)

    # Process exits here — OS destroys the window cleanly.


def _replay_best_match(
    config: Config,
    engine: EvolutionEngine,
    populations: dict[int, list[BehaviorTree]],
    gen_result: GenerationResult,
) -> bool:
    """Replay the best-vs-best match in a subprocess. Returns False if user quit early."""
    team_ids = sorted(populations.keys())
    if len(team_ids) < 2:
        return True

    # Find best strategy per team and serialize for the child process
    best_data: dict[int, dict] = {}
    comp_strs: dict[int, str] = {}
    for tid in team_ids:
        fitnesses = gen_result.fitnesses[tid]
        best_idx = fitnesses.index(max(fitnesses))
        best_data[tid] = serialize_tree(populations[tid][best_idx])
        comp_strs[tid] = _format_composition(populations[tid][best_idx].composition)

    # Determine arena preset for this generation
    if config.arena.rotate_presets and config.arena.preset_rotation:
        presets = config.arena.preset_rotation
        arena_preset = presets[gen_result.generation % len(presets)]
    else:
        arena_preset = config.arena.preset

    print(f"\n  Replaying Gen {gen_result.generation} best: "
          f"T0 ({comp_strs[team_ids[0]]}) vs T1 ({comp_strs[team_ids[1]]})")

    proc = multiprocessing.Process(
        target=_replay_in_subprocess,
        args=(config, best_data[team_ids[0]], best_data[team_ids[1]],
              gen_result.generation, arena_preset),
    )
    proc.start()
    proc.join()

    # exitcode 0 = normal finish, negative = killed by signal
    return proc.exitcode == 0


def run_evolution(config: Config) -> None:
    """Run the full evolution loop with terminal output and optional replays."""
    engine = EvolutionEngine(config)
    rng = random.Random(config.seed)

    show_every = config.visualization.show_every_n_generations
    show_battles = config.visualization.enabled

    print(f"Evolution Tank — Evolution Mode")
    print(f"Seed: {config.seed}")
    print(f"Arena: {config.arena.width}x{config.arena.height}, "
          f"Presets: {', '.join(config.arena.preset_rotation)}")
    print(f"Teams: {config.match.team_count} x {config.match.team_size} tanks")
    print(f"Population: {config.evolution.population_size}, "
          f"Generations: {config.evolution.generations}")
    print(f"Composition evolution: {'ON' if config.evolution.composition.enabled else 'OFF'}")
    if show_battles:
        print(f"Replaying best-vs-best every {show_every} generations")
    else:
        print(f"Headless mode (no replays)")
    print(f"Match max ticks: {config.match.max_ticks}")
    print("-" * 72, flush=True)

    populations = engine.initialize_populations(rng)
    collector = AnalyticsCollector(config.analytics)

    start_time = time.time()

    def _match_progress(done: int, total: int) -> None:
        import sys
        sys.stderr.write(f"\r  Gen {gen}: match {done}/{total}  ")
        sys.stderr.flush()

    try:
        for gen in range(config.evolution.generations):
            gen_result = engine.run_generation(populations, gen, rng, _match_progress)
            import sys
            sys.stderr.write("\r" + " " * 40 + "\r")
            sys.stderr.flush()
            _print_generation(gen_result, populations)
            collector.on_generation(gen_result, populations)

            # Show battle replay at configured intervals
            if show_battles and gen % show_every == 0:
                user_continued = _replay_best_match(
                    config, engine, populations, gen_result,
                )
                if not user_continued:
                    print("  (Viewer closed — continuing headless)")
                    show_battles = False

            # Evolve to next generation (skip on last)
            if gen < config.evolution.generations - 1:
                populations = engine.evolve(
                    populations, gen_result.fitnesses, rng,
                )

        elapsed = time.time() - start_time
        print("-" * 72)
        print(f"Evolution complete in {elapsed:.1f}s")
        collector.finalize()

        # Final best-vs-best replay
        if show_battles:
            print("Final best-vs-best replay:")
            final_result = engine.run_generation(populations, config.evolution.generations - 1, rng)
            _replay_best_match(config, engine, populations, final_result)

    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\nInterrupted at gen {gen} after {elapsed:.1f}s")
        collector.finalize()
