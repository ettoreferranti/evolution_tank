"""BehaviorTree — wraps a root node, provides StrategyFn adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from evolution_tank.simulation.match import TankCommand
from evolution_tank.strategy.nodes import BTNode, TickContext, TreeMemory

if TYPE_CHECKING:
    from evolution_tank.simulation.arena import Arena
    from evolution_tank.simulation.fog_of_war import SensorSnapshot
    from evolution_tank.simulation.match import StrategyFn
    from evolution_tank.tanks.tank import Tank


class BehaviorTree:
    """A complete behavior tree strategy.

    Wraps a root BTNode, optional team composition, and per-match memory.
    Call evaluate() each tick, or use to_strategy_fn() for integration
    with the match runner.
    """

    def __init__(self, root: BTNode,
                 composition: dict[str, int] | None = None) -> None:
        self.root = root
        self.composition = composition  # e.g. {"light": 2, "medium": 2, "heavy": 1}
        self.memory = TreeMemory()

    def reset(self) -> None:
        """Reset runtime memory. Call between matches."""
        self.memory.reset()

    def evaluate(self, tank: Tank, sensor: SensorSnapshot,
                 arena: Arena, tick: int = 0) -> TankCommand:
        """Evaluate the tree for one tick, returning the assembled command."""
        command = TankCommand()

        # Update memory with current observations
        if sensor.visible_enemies:
            nearest = min(sensor.visible_enemies, key=lambda e: e.distance)
            self.memory.last_known_enemy_pos = nearest.position
            self.memory.last_known_enemy_tick = tick

        ctx = TickContext(
            tank=tank,
            sensor=sensor,
            command=command,
            arena=arena,
            memory=self.memory,
            tick=tick,
        )
        self.root.tick(ctx)
        return ctx.command

    def to_strategy_fn(self, arena: Arena) -> StrategyFn:
        """Create a StrategyFn compatible with match.run_match."""
        tree = self
        tick_counter = [0]

        def strategy(tank: Tank, sensor: SensorSnapshot) -> TankCommand:
            tick_counter[0] += 1
            return tree.evaluate(tank, sensor, arena, tick_counter[0])

        return strategy

    def to_dict(self) -> dict[str, Any]:
        data = self.root.to_dict()
        if self.composition is not None:
            data["composition"] = dict(self.composition)
        return data
