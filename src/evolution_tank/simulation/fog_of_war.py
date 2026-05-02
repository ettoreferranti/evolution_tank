"""Fog of war — visibility, line-of-sight, sensor data."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from evolution_tank.simulation.arena import Arena, Vector2
from evolution_tank.tanks.tank import Tank, TankType

if TYPE_CHECKING:
    from evolution_tank.config import FogOfWarConfig


@dataclass(frozen=True)
class EnemySensorData:
    """What a tank knows about a visible enemy."""
    tank_id: int
    tank_type: TankType
    position: Vector2
    distance: float
    angle: float              # degrees from observer
    heading: float            # enemy hull heading
    turret_angle: float       # enemy turret angle (absolute)
    velocity: Vector2         # enemy velocity vector (for lead calculation)
    is_repairing: bool


@dataclass(frozen=True)
class AllySensorData:
    """What a tank knows about a visible ally."""
    tank_id: int
    tank_type: TankType
    position: Vector2
    distance: float
    is_repairing: bool


@dataclass
class SensorSnapshot:
    """Full sensor data for a single tank at one tick."""
    visible_enemies: list[EnemySensorData]
    visible_allies: list[AllySensorData]
    under_fire: bool  # Was this tank hit recently?
    signals: list = field(default_factory=list)  # Team Signal objects


def compute_sensor_data(
    observer: Tank,
    all_tanks: list[Tank],
    arena: Arena,
    fog_config: FogOfWarConfig,
    recently_hit_ids: set[int],
    signals: list | None = None,
) -> SensorSnapshot:
    """Compute what one tank can see.

    If team vision sharing is enabled, the observer sees the union of
    what all living allies can see.
    """
    if not observer.is_alive:
        return SensorSnapshot([], [], False)

    # Determine which tanks are observers (for team vision sharing)
    if fog_config.enabled and fog_config.share_team_vision:
        observers = [
            t for t in all_tanks
            if t.team_id == observer.team_id and t.is_alive
        ]
    else:
        observers = [observer]

    visible_enemies: list[EnemySensorData] = []
    visible_allies: list[AllySensorData] = []
    seen_ids: set[int] = set()

    for obs in observers:
        vis_range = obs.type_config.visibility_range

        for target in all_tanks:
            if target.id == observer.id:
                continue
            if not target.is_alive:
                continue
            if target.id in seen_ids:
                continue

            dist = obs.position.distance_to(target.position)

            # Range check (skip if fog is disabled)
            if fog_config.enabled and dist > vis_range:
                continue

            # Line of sight check
            if fog_config.enabled and not _has_line_of_sight(obs.position, target.position, arena):
                continue

            seen_ids.add(target.id)

            if target.team_id == observer.team_id:
                visible_allies.append(AllySensorData(
                    tank_id=target.id,
                    tank_type=target.tank_type,
                    position=target.position,
                    distance=dist,
                    is_repairing=target.is_repairing,
                ))
            else:
                # Compute angle from observer (not from the detecting ally)
                diff = target.position - observer.position
                angle = diff.angle()
                dist_from_observer = observer.position.distance_to(target.position)

                visible_enemies.append(EnemySensorData(
                    tank_id=target.id,
                    tank_type=target.tank_type,
                    position=target.position,
                    distance=dist_from_observer,
                    angle=angle,
                    heading=target.heading,
                    turret_angle=target.turret_angle,
                    velocity=target.velocity,
                    is_repairing=target.is_repairing,
                ))

    under_fire = observer.id in recently_hit_ids

    # Filter signals to this tank's team
    team_signals = []
    if signals:
        team_signals = [s for s in signals if s.team_id == observer.team_id]

    return SensorSnapshot(
        visible_enemies=visible_enemies,
        visible_allies=visible_allies,
        under_fire=under_fire,
        signals=team_signals,
    )


def _has_line_of_sight(start: Vector2, end: Vector2, arena: Arena) -> bool:
    """Check if there's a clear line of sight between two points.

    Raycast through the grid, checking for wall cells.
    """
    diff = end - start
    length = diff.length()
    if length < 1e-6:
        return True

    # Step at half-cell intervals for accuracy
    step_size = arena.cell_size / 2
    steps = max(1, int(length / step_size))
    for i in range(1, steps):
        t = i / steps
        point = start + diff * t
        if arena.blocks_los(point):
            return False
    return True
