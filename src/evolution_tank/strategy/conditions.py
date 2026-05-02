"""Condition nodes — read-only checks that return SUCCESS or FAILURE."""

from __future__ import annotations

import math
from typing import Any

from evolution_tank.simulation.arena import Vector2
from evolution_tank.strategy.nodes import BTNode, NodeStatus, TickContext


class EnemyVisible(BTNode):
    """SUCCESS if at least one enemy is visible."""

    def tick(self, ctx: TickContext) -> NodeStatus:
        if ctx.sensor.visible_enemies:
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {"type": "enemy_visible"}


class HealthBelow(BTNode):
    """SUCCESS if tank HP is below a fraction of max HP.

    Args:
        threshold: 0.0–1.0 fraction of max HP.
    """

    def __init__(self, threshold: float = 0.3) -> None:
        self.threshold = max(0.0, min(1.0, threshold))

    def tick(self, ctx: TickContext) -> NodeStatus:
        if ctx.tank.hp / ctx.tank.max_hp < self.threshold:
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {"type": "health_below", "params": {"threshold": self.threshold}}

    def get_params(self) -> dict[str, float | str]:
        return {"threshold": self.threshold}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "threshold" in params:
            self.threshold = max(0.0, min(1.0, float(params["threshold"])))


class AmmoBelow(BTNode):
    """SUCCESS if tank ammo is below a count.

    Args:
        count: Absolute ammo count threshold.
    """

    def __init__(self, count: float = 5.0) -> None:
        self.count = max(0.0, count)

    def tick(self, ctx: TickContext) -> NodeStatus:
        if ctx.tank.ammo < self.count:
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {"type": "ammo_below", "params": {"count": self.count}}

    def get_params(self) -> dict[str, float | str]:
        return {"count": self.count}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "count" in params:
            self.count = max(0.0, float(params["count"]))


class AllyNearby(BTNode):
    """SUCCESS if at least one ally is within distance.

    Args:
        distance: Maximum distance in pixels.
    """

    def __init__(self, distance: float = 100.0) -> None:
        self.distance = max(0.0, distance)

    def tick(self, ctx: TickContext) -> NodeStatus:
        for ally in ctx.sensor.visible_allies:
            if ally.distance <= self.distance:
                return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {"type": "ally_nearby", "params": {"distance": self.distance}}

    def get_params(self) -> dict[str, float | str]:
        return {"distance": self.distance}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "distance" in params:
            self.distance = max(0.0, float(params["distance"]))


class UnderFire(BTNode):
    """SUCCESS if the tank was hit recently."""

    def tick(self, ctx: TickContext) -> NodeStatus:
        if ctx.sensor.under_fire:
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {"type": "under_fire"}


class TurretAimedAtMe(BTNode):
    """SUCCESS if any visible enemy's turret points within tolerance of us.

    Args:
        tolerance: Degrees of angular tolerance.
    """

    def __init__(self, tolerance: float = 15.0) -> None:
        self.tolerance = max(1.0, min(90.0, tolerance))

    def tick(self, ctx: TickContext) -> NodeStatus:
        for enemy in ctx.sensor.visible_enemies:
            # Angle from enemy to us
            diff = ctx.tank.position - enemy.position
            angle_to_us = diff.angle()
            # How far off is the enemy's turret from pointing at us?
            delta = abs(enemy.turret_angle - angle_to_us) % 360
            if delta > 180:
                delta = 360 - delta
            if delta <= self.tolerance:
                return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {"type": "turret_aimed_at_me", "params": {"tolerance": self.tolerance}}

    def get_params(self) -> dict[str, float | str]:
        return {"tolerance": self.tolerance}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "tolerance" in params:
            self.tolerance = max(1.0, min(90.0, float(params["tolerance"])))


class InRange(BTNode):
    """SUCCESS if any visible enemy is within distance.

    Args:
        distance: Maximum distance in pixels.
    """

    def __init__(self, distance: float = 150.0) -> None:
        self.distance = max(0.0, distance)

    def tick(self, ctx: TickContext) -> NodeStatus:
        for enemy in ctx.sensor.visible_enemies:
            if enemy.distance <= self.distance:
                return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {"type": "in_range", "params": {"distance": self.distance}}

    def get_params(self) -> dict[str, float | str]:
        return {"distance": self.distance}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "distance" in params:
            self.distance = max(0.0, float(params["distance"]))


class NearCover(BTNode):
    """SUCCESS if a wall cell is within distance of the tank.

    Args:
        distance: Maximum distance in pixels to scan for walls.
    """

    def __init__(self, distance: float = 60.0) -> None:
        self.distance = max(0.0, min(200.0, distance))

    def tick(self, ctx: TickContext) -> NodeStatus:
        pos = ctx.tank.position
        arena = ctx.arena
        cell_size = arena.cell_size
        # Scan nearby cells within distance
        scan_cells = int(self.distance / cell_size) + 1
        center_col = int(pos.x / cell_size)
        center_row = int(pos.y / cell_size)

        for dr in range(-scan_cells, scan_cells + 1):
            for dc in range(-scan_cells, scan_cells + 1):
                r, c = center_row + dr, center_col + dc
                if 0 <= r < arena.rows and 0 <= c < arena.cols:
                    if arena.blocks_los(arena.cell_center(r, c)):
                        wall_pos = arena.cell_center(r, c)
                        if pos.distance_to(wall_pos) <= self.distance:
                            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {"type": "near_cover", "params": {"distance": self.distance}}

    def get_params(self) -> dict[str, float | str]:
        return {"distance": self.distance}

    def set_params(self, params: dict[str, float | str]) -> None:
        if "distance" in params:
            self.distance = max(0.0, min(200.0, float(params["distance"])))
