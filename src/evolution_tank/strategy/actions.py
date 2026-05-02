"""Action nodes — mutate TankCommand fields, return SUCCESS/FAILURE."""

from __future__ import annotations

import math
from typing import Any

from evolution_tank.simulation.arena import Vector2
from evolution_tank.simulation.physics import compute_wall_avoidance
from evolution_tank.strategy.nodes import (
    BTNode,
    NodeStatus,
    TargetSelector,
    TickContext,
    resolve_target,
)
from evolution_tank.tanks.tank import Tank


# ---------------------------------------------------------------------------
# Movement actions
# ---------------------------------------------------------------------------

class MoveToward(BTNode):
    """Move toward a target. Sets desired_heading and desired_speed.

    Args:
        target: Which target to move toward.
        speed: Desired speed fraction (0.0–1.0).
    """

    def __init__(self, target: TargetSelector = TargetSelector.NEAREST_ENEMY,
                 speed: float = 0.8) -> None:
        self.target = target
        self.speed = max(0.0, min(1.0, speed))

    def tick(self, ctx: TickContext) -> NodeStatus:
        pos = resolve_target(self.target, ctx)
        if pos is None:
            return NodeStatus.FAILURE
        diff = pos - ctx.tank.position
        if diff.length() < 1e-6:
            return NodeStatus.SUCCESS
        heading = compute_wall_avoidance(ctx.tank, diff.angle(), ctx.arena)
        ctx.command.desired_heading = heading
        ctx.command.desired_speed = self.speed
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {"type": "move_toward", "params": {
            "target": self.target.value, "speed": self.speed,
        }}

    def get_params(self) -> dict[str, float | str]:
        return {"target": self.target.value, "speed": self.speed}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "target" in params:
            self.target = TargetSelector(params["target"])
        if "speed" in params:
            self.speed = max(0.0, min(1.0, float(params["speed"])))


class MoveAway(BTNode):
    """Move away from a target. Sets desired_heading and desired_speed.

    Args:
        target: Which target to flee from.
        speed: Desired speed fraction (0.0–1.0).
    """

    def __init__(self, target: TargetSelector = TargetSelector.NEAREST_ENEMY,
                 speed: float = 1.0) -> None:
        self.target = target
        self.speed = max(0.0, min(1.0, speed))

    def tick(self, ctx: TickContext) -> NodeStatus:
        pos = resolve_target(self.target, ctx)
        if pos is None:
            return NodeStatus.FAILURE
        diff = ctx.tank.position - pos  # Away from target
        if diff.length() < 1e-6:
            return NodeStatus.SUCCESS
        heading = compute_wall_avoidance(ctx.tank, diff.angle(), ctx.arena)
        ctx.command.desired_heading = heading
        ctx.command.desired_speed = self.speed
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {"type": "move_away", "params": {
            "target": self.target.value, "speed": self.speed,
        }}

    def get_params(self) -> dict[str, float | str]:
        return {"target": self.target.value, "speed": self.speed}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "target" in params:
            self.target = TargetSelector(params["target"])
        if "speed" in params:
            self.speed = max(0.0, min(1.0, float(params["speed"])))


class Patrol(BTNode):
    """Patrol toward waypoints around the arena center.

    Args:
        speed: Desired speed fraction (0.0–1.0).
    """

    # Waypoints as fractions of arena size
    _WAYPOINT_FRACTIONS = [
        (0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75),
    ]

    def __init__(self, speed: float = 0.6) -> None:
        self.speed = max(0.0, min(1.0, speed))

    def tick(self, ctx: TickContext) -> NodeStatus:
        waypoints = [
            Vector2(fx * ctx.arena.width, fy * ctx.arena.height)
            for fx, fy in self._WAYPOINT_FRACTIONS
        ]
        idx = ctx.memory.patrol_waypoint_index % len(waypoints)
        target = waypoints[idx]

        diff = target - ctx.tank.position
        if diff.length() < 30.0:
            # Reached waypoint, advance to next
            ctx.memory.patrol_waypoint_index = (idx + 1) % len(waypoints)
            target = waypoints[ctx.memory.patrol_waypoint_index]
            diff = target - ctx.tank.position

        heading = compute_wall_avoidance(ctx.tank, diff.angle(), ctx.arena)
        ctx.command.desired_heading = heading
        ctx.command.desired_speed = self.speed
        ctx.command.desired_turret_angle = diff.angle()
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {"type": "patrol", "params": {"speed": self.speed}}

    def get_params(self) -> dict[str, float | str]:
        return {"speed": self.speed}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "speed" in params:
            self.speed = max(0.0, min(1.0, float(params["speed"])))


class SeekCover(BTNode):
    """Move toward the nearest wall to use as cover from the nearest enemy."""

    def tick(self, ctx: TickContext) -> NodeStatus:
        pos = ctx.tank.position
        arena = ctx.arena
        cell_size = arena.cell_size

        # Find nearest enemy direction (to position cover between us and them)
        enemy_dir: Vector2 | None = None
        if ctx.sensor.visible_enemies:
            nearest = min(ctx.sensor.visible_enemies, key=lambda e: e.distance)
            enemy_dir = nearest.position - pos

        # Scan for nearby wall cells
        scan_cells = 5
        center_col = int(pos.x / cell_size)
        center_row = int(pos.y / cell_size)

        best_pos: Vector2 | None = None
        best_score = float("inf")

        for dr in range(-scan_cells, scan_cells + 1):
            for dc in range(-scan_cells, scan_cells + 1):
                r, c = center_row + dr, center_col + dc
                if 0 <= r < arena.rows and 0 <= c < arena.cols:
                    if arena.blocks_los(arena.cell_center(r, c)):
                        # Check adjacent passable cells as cover positions
                        for ar, ac in [(r-1, c), (r+1, c), (r, c-1), (r, c+1)]:
                            if 0 <= ar < arena.rows and 0 <= ac < arena.cols:
                                adj_pos = arena.cell_center(ar, ac)
                                if arena.is_passable(adj_pos):
                                    dist = pos.distance_to(adj_pos)
                                    # Prefer cover that is between us and the enemy
                                    score = dist
                                    if enemy_dir is not None:
                                        wall_center = arena.cell_center(r, c)
                                        # Is the wall between adj_pos and enemy?
                                        to_wall = wall_center - adj_pos
                                        if enemy_dir.length() > 1e-6 and to_wall.length() > 1e-6:
                                            # Prefer positions where wall is toward enemy
                                            alignment = to_wall.normalized().dot(enemy_dir.normalized())
                                            score = dist * (2.0 - alignment)
                                    if score < best_score:
                                        best_score = score
                                        best_pos = adj_pos

        if best_pos is None:
            return NodeStatus.FAILURE

        diff = best_pos - pos
        heading = compute_wall_avoidance(ctx.tank, diff.angle(), ctx.arena)
        ctx.command.desired_heading = heading
        ctx.command.desired_speed = 0.8
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {"type": "seek_cover"}


# ---------------------------------------------------------------------------
# Turret / combat actions
# ---------------------------------------------------------------------------

class AimAt(BTNode):
    """Aim turret at a target with lead prediction.

    Args:
        target: Which target to aim at.
    """

    def __init__(self, target: TargetSelector = TargetSelector.NEAREST_ENEMY) -> None:
        self.target = target

    def tick(self, ctx: TickContext) -> NodeStatus:
        if self.target in (TargetSelector.NEAREST_ENEMY, TargetSelector.LAST_KNOWN_ENEMY):
            # For enemies, use lead prediction
            enemy = self._pick_enemy(ctx)
            if enemy is not None:
                lead = Tank.compute_lead_angle(
                    ctx.tank.position, enemy.position, enemy.velocity,
                    ctx.tank.type_config.projectile_speed,
                )
                if lead is not None:
                    ctx.command.desired_turret_angle = lead
                else:
                    ctx.command.desired_turret_angle = (enemy.position - ctx.tank.position).angle()
                return NodeStatus.SUCCESS

            # Fall through to generic target resolution for last_known_enemy
            if self.target == TargetSelector.LAST_KNOWN_ENEMY:
                pos = resolve_target(self.target, ctx)
                if pos is not None:
                    ctx.command.desired_turret_angle = (pos - ctx.tank.position).angle()
                    return NodeStatus.SUCCESS
            return NodeStatus.FAILURE

        # Generic position-based aiming (allies, signals)
        pos = resolve_target(self.target, ctx)
        if pos is None:
            return NodeStatus.FAILURE
        ctx.command.desired_turret_angle = (pos - ctx.tank.position).angle()
        return NodeStatus.SUCCESS

    def _pick_enemy(self, ctx: TickContext) -> Any:
        """Pick the target enemy from visible enemies."""
        if not ctx.sensor.visible_enemies:
            return None
        return min(ctx.sensor.visible_enemies, key=lambda e: e.distance)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "aim_at", "params": {"target": self.target.value}}

    def get_params(self) -> dict[str, float | str]:
        return {"target": self.target.value}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "target" in params:
            self.target = TargetSelector(params["target"])


class Fire(BTNode):
    """Set fire=True on the command. Always succeeds."""

    def tick(self, ctx: TickContext) -> NodeStatus:
        ctx.command.fire = True
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {"type": "fire"}


class Repair(BTNode):
    """Set repair=True on the command. Always succeeds."""

    def tick(self, ctx: TickContext) -> NodeStatus:
        ctx.command.repair = True
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {"type": "repair"}


# ---------------------------------------------------------------------------
# Communication actions
# ---------------------------------------------------------------------------

class SignalAction(BTNode):
    """Send a signal to allies.

    Args:
        signal_type: The signal type string.
    """

    def __init__(self, signal_type: str = "ENEMY_SPOTTED") -> None:
        self.signal_type = signal_type

    def tick(self, ctx: TickContext) -> NodeStatus:
        ctx.command.signal_type = self.signal_type
        ctx.command.signal_position = ctx.tank.position
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {"type": "signal", "params": {"signal_type": self.signal_type}}

    def get_params(self) -> dict[str, float | str]:
        return {"signal_type": self.signal_type}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "signal_type" in params:
            self.signal_type = str(params["signal_type"])


class MoveToSignal(BTNode):
    """Move toward the most recent team signal position.

    Args:
        speed: Desired speed fraction (0.0–1.0).
    """

    def __init__(self, speed: float = 0.8) -> None:
        self.speed = max(0.0, min(1.0, speed))

    def tick(self, ctx: TickContext) -> NodeStatus:
        pos = resolve_target(TargetSelector.SIGNAL_POSITION, ctx)
        if pos is None:
            return NodeStatus.FAILURE
        diff = pos - ctx.tank.position
        if diff.length() < 1e-6:
            return NodeStatus.SUCCESS
        heading = compute_wall_avoidance(ctx.tank, diff.angle(), ctx.arena)
        ctx.command.desired_heading = heading
        ctx.command.desired_speed = self.speed
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {"type": "move_to_signal", "params": {"speed": self.speed}}

    def get_params(self) -> dict[str, float | str]:
        return {"speed": self.speed}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "speed" in params:
            self.speed = max(0.0, min(1.0, float(params["speed"])))
