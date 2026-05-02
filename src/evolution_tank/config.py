"""Configuration system — loads YAML settings, validates, provides immutable Config."""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Defaults — mirrors config/settings.yaml structure
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "seed": None,
    "arena": {
        "width": 800,
        "height": 800,
        "preset": "default",
        "rotate_presets": True,
        "preset_rotation": ["default", "open", "maze", "corridors"],
        "terrain_types": {
            "open": {"speed_modifier": 1.0, "passable": True, "blocks_los": False},
            "wall": {"speed_modifier": 0.0, "passable": False, "blocks_los": True},
            "mud": {"speed_modifier": 0.5, "passable": True, "blocks_los": False},
            "road": {"speed_modifier": 1.3, "passable": True, "blocks_los": False},
        },
    },
    "tank_types": {
        "light": {
            "hp": 50, "armor": 5, "speed": 5.0, "acceleration": 3.0,
            "turn_rate": 180, "turret_rotation_speed": 240,
            "reload_time": 8.0, "damage": 20, "ammo": 20,
            "visibility_range": 250, "repair_time": 15.0,
            "projectile_speed": 10.0, "projectile_range": 300,
        },
        "medium": {
            "hp": 100, "armor": 15, "speed": 3.5, "acceleration": 2.0,
            "turn_rate": 120, "turret_rotation_speed": 180,
            "reload_time": 12.0, "damage": 45, "ammo": 15,
            "visibility_range": 200, "repair_time": 20.0,
            "projectile_speed": 8.0, "projectile_range": 400,
        },
        "heavy": {
            "hp": 200, "armor": 30, "speed": 2.0, "acceleration": 1.0,
            "turn_rate": 60, "turret_rotation_speed": 90,
            "reload_time": 20.0, "damage": 100, "ammo": 10,
            "visibility_range": 150, "repair_time": 30.0,
            "projectile_speed": 6.0, "projectile_range": 500,
        },
    },
    "match": {
        "team_count": 2,
        "team_size": 5,
        "free_for_all": False,
        "max_ticks": 36000,
        "best_of": 3,
        "ticks_per_second": 60,
        "spawn": {
            "side": "opposite",
            "min_separation": 30,
            "cluster_spread": 50,
        },
    },
    "fog_of_war": {
        "enabled": True,
        "share_team_vision": True,
    },
    "combat": {
        "friendly_fire": True,
    },
    "evolution": {
        "population_size": 100,
        "generations": 100,
        "tournament_size": 5,
        "elitism_count": 5,
        "matches_per_strategy": 5,
        "crossover_rate": 0.7,
        "max_tree_depth": 8,
        "composition": {
            "enabled": True,
            "fixed_composition": {"light": 2, "medium": 2, "heavy": 1},
        },
        "initial_population": {
            "mode": "random",
            "seed_file": None,
            "seed_count": 10,
        },
        "mutation": {
            "parameter_rate": 0.3,
            "parameter_sigma": 0.1,
            "structural_rate": 0.05,
            "insert_weight": 1.0,
            "delete_weight": 1.0,
            "swap_weight": 0.5,
            "replace_weight": 0.5,
        },
    },
    "fitness": {
        "weights": {
            "win": 10.0,
            "damage_dealt": 1.0,
            "friendly_fire": -2.0,
            "damage_taken": -0.5,
            "survival_time": 0.1,
            "ammo_efficiency": 2.0,
            "team_coordination": 1.0,
        },
    },
    "communication": {
        "enabled": True,
        "signal_types": ["ENEMY_SPOTTED", "HELP", "REGROUP", "ATTACK_HERE"],
        "signal_range_multiplier": 1.0,
    },
    "analytics": {
        "output_dir": "output",
        "save_fitness_csv": True,
        "save_lineage": True,
        "save_diversity": True,
        "save_win_matrix": True,
        "plot_fitness_curves": True,
        "log_every_n_generations": 1,
    },
    "visualization": {
        "enabled": True,
        "window_width": 1024,
        "window_height": 768,
        "show_fog_of_war": True,
        "show_hp_bars": True,
        "default_speed": 5,
        "show_every_n_generations": 10,
        "colors": {
            "open": [34, 139, 34],
            "wall": [64, 64, 64],
            "mud": [139, 119, 42],
            "road": [169, 169, 169],
            "team_colors": [
                [65, 105, 225],
                [220, 20, 60],
                [50, 205, 50],
                [255, 165, 0],
            ],
        },
    },
}


# ---------------------------------------------------------------------------
# Frozen dataclass hierarchy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TerrainTypeConfig:
    speed_modifier: float
    passable: bool
    blocks_los: bool


@dataclass(frozen=True)
class TankTypeConfig:
    hp: int
    armor: int
    speed: float
    acceleration: float
    turn_rate: float
    turret_rotation_speed: float
    reload_time: float
    damage: int
    ammo: int
    visibility_range: float
    repair_time: float
    projectile_speed: float
    projectile_range: float


@dataclass(frozen=True)
class ArenaConfig:
    width: int
    height: int
    preset: str
    rotate_presets: bool
    preset_rotation: tuple[str, ...]
    terrain_types: dict[str, TerrainTypeConfig]


@dataclass(frozen=True)
class SpawnConfig:
    side: str
    min_separation: float
    cluster_spread: float


@dataclass(frozen=True)
class MatchConfig:
    team_count: int
    team_size: int
    free_for_all: bool
    max_ticks: int
    best_of: int
    ticks_per_second: int
    spawn: SpawnConfig


@dataclass(frozen=True)
class FogOfWarConfig:
    enabled: bool
    share_team_vision: bool


@dataclass(frozen=True)
class CombatConfig:
    friendly_fire: bool


@dataclass(frozen=True)
class MutationConfig:
    parameter_rate: float
    parameter_sigma: float
    structural_rate: float
    insert_weight: float
    delete_weight: float
    swap_weight: float
    replace_weight: float


@dataclass(frozen=True)
class CompositionConfig:
    enabled: bool
    fixed_composition: dict[str, int]


@dataclass(frozen=True)
class InitialPopulationConfig:
    mode: str
    seed_file: str | None
    seed_count: int


@dataclass(frozen=True)
class EvolutionConfig:
    population_size: int
    generations: int
    tournament_size: int
    elitism_count: int
    matches_per_strategy: int
    crossover_rate: float
    max_tree_depth: int
    composition: CompositionConfig
    initial_population: InitialPopulationConfig
    mutation: MutationConfig


@dataclass(frozen=True)
class FitnessWeights:
    win: float
    damage_dealt: float
    friendly_fire: float
    damage_taken: float
    survival_time: float
    ammo_efficiency: float
    team_coordination: float


@dataclass(frozen=True)
class FitnessConfig:
    weights: FitnessWeights


@dataclass(frozen=True)
class CommunicationConfig:
    enabled: bool
    signal_types: tuple[str, ...]
    signal_range_multiplier: float


@dataclass(frozen=True)
class AnalyticsConfig:
    output_dir: str
    save_fitness_csv: bool
    save_lineage: bool
    save_diversity: bool
    save_win_matrix: bool
    plot_fitness_curves: bool
    log_every_n_generations: int


@dataclass(frozen=True)
class VisualizationColors:
    open: tuple[int, int, int]
    wall: tuple[int, int, int]
    mud: tuple[int, int, int]
    road: tuple[int, int, int]
    team_colors: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class VisualizationConfig:
    enabled: bool
    window_width: int
    window_height: int
    show_fog_of_war: bool
    show_hp_bars: bool
    default_speed: int
    show_every_n_generations: int
    colors: VisualizationColors


@dataclass(frozen=True)
class Config:
    seed: int
    arena: ArenaConfig
    tank_types: dict[str, TankTypeConfig]
    match: MatchConfig
    fog_of_war: FogOfWarConfig
    combat: CombatConfig
    evolution: EvolutionConfig
    fitness: FitnessConfig
    communication: CommunicationConfig
    analytics: AnalyticsConfig
    visualization: VisualizationConfig

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Load config from YAML file, falling back to defaults."""
        merged = copy.deepcopy(_DEFAULTS)
        if path is not None:
            path = Path(path)
            if not path.exists():
                raise FileNotFoundError(f"Config file not found: {path}")
            with open(path) as f:
                overrides = yaml.safe_load(f) or {}
            _deep_merge(merged, overrides)
        return _build_config(merged)

    # ------------------------------------------------------------------
    # Immutable "with" helpers — return a new Config with one field changed
    # ------------------------------------------------------------------

    def with_seed(self, seed: int) -> Config:
        return Config(
            seed=seed,
            arena=self.arena,
            tank_types=self.tank_types,
            match=self.match,
            fog_of_war=self.fog_of_war,
            combat=self.combat,
            evolution=self.evolution,
            fitness=self.fitness,
            communication=self.communication,
            analytics=self.analytics,
            visualization=self.visualization,
        )

    def with_visualization(self, enabled: bool) -> Config:
        new_viz = VisualizationConfig(
            enabled=enabled,
            window_width=self.visualization.window_width,
            window_height=self.visualization.window_height,
            show_fog_of_war=self.visualization.show_fog_of_war,
            show_hp_bars=self.visualization.show_hp_bars,
            default_speed=self.visualization.default_speed,
            show_every_n_generations=self.visualization.show_every_n_generations,
            colors=self.visualization.colors,
        )
        return Config(
            seed=self.seed,
            arena=self.arena,
            tank_types=self.tank_types,
            match=self.match,
            fog_of_war=self.fog_of_war,
            combat=self.combat,
            evolution=self.evolution,
            fitness=self.fitness,
            communication=self.communication,
            analytics=self.analytics,
            visualization=new_viz,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base, mutating base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _build_config(d: dict[str, Any]) -> Config:
    """Build the frozen Config hierarchy from a raw dict."""
    # Seed
    seed = d["seed"] if d["seed"] is not None else random.randint(0, 2**31 - 1)

    # Arena
    _validate_range("arena.width", d["arena"]["width"], 400, 2000)
    _validate_range("arena.height", d["arena"]["height"], 400, 2000)
    terrain_types = {
        name: TerrainTypeConfig(**props)
        for name, props in d["arena"]["terrain_types"].items()
    }
    arena = ArenaConfig(
        width=d["arena"]["width"],
        height=d["arena"]["height"],
        preset=d["arena"]["preset"],
        rotate_presets=d["arena"]["rotate_presets"],
        preset_rotation=tuple(d["arena"]["preset_rotation"]),
        terrain_types=terrain_types,
    )

    # Tank types
    tank_types = {}
    for name, props in d["tank_types"].items():
        _validate_positive(f"tank_types.{name}.hp", props["hp"])
        _validate_positive(f"tank_types.{name}.speed", props["speed"])
        _validate_positive(f"tank_types.{name}.ammo", props["ammo"])
        _validate_positive(f"tank_types.{name}.projectile_speed", props["projectile_speed"])
        tank_types[name] = TankTypeConfig(**props)

    # Match
    _validate_range("match.team_size", d["match"]["team_size"], 1, 10)
    _validate_positive("match.team_count", d["match"]["team_count"])
    _validate_positive("match.best_of", d["match"]["best_of"])
    _validate_positive("match.ticks_per_second", d["match"]["ticks_per_second"])
    spawn = SpawnConfig(**d["match"]["spawn"])
    match = MatchConfig(
        team_count=d["match"]["team_count"],
        team_size=d["match"]["team_size"],
        free_for_all=d["match"]["free_for_all"],
        max_ticks=d["match"]["max_ticks"],
        best_of=d["match"]["best_of"],
        ticks_per_second=d["match"]["ticks_per_second"],
        spawn=spawn,
    )

    # Fog of war
    fog_of_war = FogOfWarConfig(**d["fog_of_war"])

    # Combat
    combat = CombatConfig(friendly_fire=d["combat"]["friendly_fire"])

    # Evolution
    evo_d = d["evolution"]
    _validate_positive("evolution.population_size", evo_d["population_size"])
    _validate_positive("evolution.generations", evo_d["generations"])
    _validate_positive("evolution.tournament_size", evo_d["tournament_size"])
    mutation = MutationConfig(**evo_d["mutation"])
    composition = CompositionConfig(
        enabled=evo_d["composition"]["enabled"],
        fixed_composition=dict(evo_d["composition"]["fixed_composition"]),
    )
    initial_population = InitialPopulationConfig(**evo_d["initial_population"])
    evolution = EvolutionConfig(
        population_size=evo_d["population_size"],
        generations=evo_d["generations"],
        tournament_size=evo_d["tournament_size"],
        elitism_count=evo_d["elitism_count"],
        matches_per_strategy=evo_d["matches_per_strategy"],
        crossover_rate=evo_d["crossover_rate"],
        max_tree_depth=evo_d["max_tree_depth"],
        composition=composition,
        initial_population=initial_population,
        mutation=mutation,
    )

    # Fitness
    fitness = FitnessConfig(weights=FitnessWeights(**d["fitness"]["weights"]))

    # Communication
    comm_d = d["communication"]
    communication = CommunicationConfig(
        enabled=comm_d["enabled"],
        signal_types=tuple(comm_d["signal_types"]),
        signal_range_multiplier=comm_d["signal_range_multiplier"],
    )

    # Analytics
    analytics = AnalyticsConfig(**d["analytics"])

    # Visualization
    viz_d = d["visualization"]
    colors = VisualizationColors(
        open=tuple(viz_d["colors"]["open"]),
        wall=tuple(viz_d["colors"]["wall"]),
        mud=tuple(viz_d["colors"]["mud"]),
        road=tuple(viz_d["colors"]["road"]),
        team_colors=tuple(tuple(c) for c in viz_d["colors"]["team_colors"]),
    )
    visualization = VisualizationConfig(
        enabled=viz_d["enabled"],
        window_width=viz_d["window_width"],
        window_height=viz_d["window_height"],
        show_fog_of_war=viz_d["show_fog_of_war"],
        show_hp_bars=viz_d["show_hp_bars"],
        default_speed=viz_d["default_speed"],
        show_every_n_generations=viz_d["show_every_n_generations"],
        colors=colors,
    )

    return Config(
        seed=seed,
        arena=arena,
        tank_types=tank_types,
        match=match,
        fog_of_war=fog_of_war,
        combat=combat,
        evolution=evolution,
        fitness=fitness,
        communication=communication,
        analytics=analytics,
        visualization=visualization,
    )


class ConfigValidationError(ValueError):
    """Raised when config values are out of bounds."""


def _validate_range(name: str, value: int | float, min_val: int | float, max_val: int | float) -> None:
    if not (min_val <= value <= max_val):
        raise ConfigValidationError(f"{name} must be between {min_val} and {max_val}, got {value}")


def _validate_positive(name: str, value: int | float) -> None:
    if value <= 0:
        raise ConfigValidationError(f"{name} must be positive, got {value}")
