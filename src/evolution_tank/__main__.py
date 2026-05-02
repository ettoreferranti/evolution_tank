"""Entry point for running evolution_tank as a module."""

import argparse
import sys
import tempfile

import yaml

from evolution_tank.config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolution Tank — evolutionary tank battle simulation")
    parser.add_argument("--config", type=str, default=None, help="Path to custom settings YAML file")
    parser.add_argument("--headless", action="store_true", help="Run without visualization")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (overrides config)")
    parser.add_argument("--evolve", action="store_true", help="Run the evolution loop")
    parser.add_argument("--generations", type=int, default=None, help="Override number of generations")
    parser.add_argument("--population", type=int, default=None, help="Override population size")
    parser.add_argument("--fast", action="store_true",
                        help="Quick evolution run (small pop, short matches, few gens)")
    args = parser.parse_args()

    config = Config.load(args.config)
    if args.seed is not None:
        config = config.with_seed(args.seed)
    if args.headless:
        config = config.with_visualization(enabled=False)

    if args.evolve:
        config = _apply_evolve_overrides(config, args)
        from evolution_tank.evolve import run_evolution
        run_evolution(config)
    else:
        # Default: run demo battle
        from evolution_tank.demo import main as demo_main
        sys.argv = _rebuild_demo_argv(args)
        demo_main()


def _apply_evolve_overrides(config: Config, args) -> Config:
    """Re-load config with CLI overrides merged in."""
    overrides: dict = {}

    if args.fast:
        overrides = {
            "match": {"team_size": 3},
            "evolution": {
                "population_size": 10,
                "generations": 5,
                "matches_per_strategy": 2,
                "tournament_size": 3,
                "elitism_count": 2,
            },
            "visualization": {"show_every_n_generations": 5},
        }

    # CLI flags override --fast defaults
    if args.generations is not None:
        overrides.setdefault("evolution", {})["generations"] = args.generations
    if args.population is not None:
        overrides.setdefault("evolution", {})["population_size"] = args.population

    if not overrides:
        return config

    # Re-load config with overrides applied
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(overrides, f)
        tmp_path = f.name
    config = Config.load(tmp_path)
    if args.seed is not None:
        config = config.with_seed(args.seed)
    if args.headless:
        config = config.with_visualization(enabled=False)
    return config


def _rebuild_demo_argv(args) -> list[str]:
    """Rebuild sys.argv for demo main, forwarding relevant flags."""
    argv = ["demo"]
    if args.seed is not None:
        argv.extend(["--seed", str(args.seed)])
    return argv


if __name__ == "__main__":
    main()
