"""Behavior tree base types — node ABC, enums, tick context."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from evolution_tank.simulation.arena import Vector2

if TYPE_CHECKING:
    from evolution_tank.simulation.arena import Arena
    from evolution_tank.simulation.fog_of_war import SensorSnapshot
    from evolution_tank.simulation.match import Signal, TankCommand
    from evolution_tank.tanks.tank import Tank


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeStatus(enum.Enum):
    """Result of evaluating a behavior tree node."""
    SUCCESS = "success"
    FAILURE = "failure"


class TargetSelector(enum.Enum):
    """How an action node picks its target."""
    NEAREST_ENEMY = "nearest_enemy"
    NEAREST_ALLY = "nearest_ally"
    LAST_KNOWN_ENEMY = "last_known_enemy"
    SIGNAL_POSITION = "signal_position"


# ---------------------------------------------------------------------------
# Per-tree runtime memory (not part of genome)
# ---------------------------------------------------------------------------

@dataclass
class TreeMemory:
    """Persistent state between ticks. Reset between matches."""
    last_known_enemy_pos: Vector2 | None = None
    last_known_enemy_tick: int = 0
    patrol_waypoint_index: int = 0

    def reset(self) -> None:
        self.last_known_enemy_pos = None
        self.last_known_enemy_tick = 0
        self.patrol_waypoint_index = 0


# ---------------------------------------------------------------------------
# Tick context — shared state for one evaluation pass
# ---------------------------------------------------------------------------

@dataclass
class TickContext:
    """Everything a node needs to make decisions and set commands."""
    tank: Tank
    sensor: SensorSnapshot
    command: TankCommand
    arena: Arena
    memory: TreeMemory
    tick: int = 0


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def resolve_target(selector: TargetSelector, ctx: TickContext) -> Vector2 | None:
    """Resolve a TargetSelector to a world position, or None if unavailable."""
    if selector == TargetSelector.NEAREST_ENEMY:
        if not ctx.sensor.visible_enemies:
            return None
        nearest = min(ctx.sensor.visible_enemies, key=lambda e: e.distance)
        return nearest.position

    if selector == TargetSelector.NEAREST_ALLY:
        if not ctx.sensor.visible_allies:
            return None
        nearest = min(ctx.sensor.visible_allies, key=lambda e: e.distance)
        return nearest.position

    if selector == TargetSelector.LAST_KNOWN_ENEMY:
        return ctx.memory.last_known_enemy_pos

    if selector == TargetSelector.SIGNAL_POSITION:
        if not ctx.sensor.signals:
            return None
        # Most recent signal from team
        team_signals = [s for s in ctx.sensor.signals
                        if s.team_id == ctx.tank.team_id]
        if not team_signals:
            return None
        return max(team_signals, key=lambda s: s.tick).position

    return None


# ---------------------------------------------------------------------------
# Abstract base node
# ---------------------------------------------------------------------------

class BTNode(ABC):
    """Abstract base for all behavior tree nodes."""

    @abstractmethod
    def tick(self, ctx: TickContext) -> NodeStatus:
        """Evaluate this node for one simulation tick."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""

    def get_params(self) -> dict[str, float | str]:
        """Return evolvable parameters (for mutation)."""
        return {}

    def set_params(self, params: dict[str, float | str]) -> None:
        """Set evolvable parameters (for mutation)."""
        pass

    def get_children(self) -> list[BTNode]:
        """Return child nodes (empty for leaf nodes)."""
        return []
