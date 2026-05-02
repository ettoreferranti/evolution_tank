"""Physics system — movement, acceleration, collision, wall avoidance."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from evolution_tank.simulation.arena import Arena, Vector2
from evolution_tank.tanks.tank import Tank

if TYPE_CHECKING:
    from evolution_tank.config import ArenaConfig

# Radius for tank-tank collision detection (pixels)
TANK_RADIUS = 8.0

# Wall avoidance: how far ahead to probe for walls
WALL_PROBE_DISTANCES = [20.0, 40.0, 60.0]  # Near, mid, far probes
WALL_AVOIDANCE_OFFSETS = [15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90, 120, -120, 150, -150]


def update_tank_movement(
    tank: Tank,
    desired_heading: float | None,
    desired_speed_fraction: float,
    arena: Arena,
    arena_config: ArenaConfig,
    dt: float,
    all_tanks: list[Tank],
) -> None:
    """Update a tank's position based on desired inputs.

    Args:
        desired_heading: Target heading in degrees, or None to keep current.
        desired_speed_fraction: 0.0 (stop) to 1.0 (full speed).
        dt: Seconds elapsed this tick.
    """
    if not tank.is_active:
        return

    # 1. Rotate hull toward desired heading
    if desired_heading is not None:
        delta = tank.desired_heading_delta(desired_heading, dt)
        tank.heading = (tank.heading + delta) % 360

    # 2. Compute target speed with terrain modifier
    terrain_mod = arena.get_speed_modifier(tank.position, arena_config)
    max_speed = tank.type_config.speed * terrain_mod
    target_speed = max_speed * max(0.0, min(1.0, desired_speed_fraction))

    # 3. Accelerate/decelerate
    current_speed = tank.speed
    accel = tank.type_config.acceleration * dt
    if target_speed > current_speed:
        new_speed = min(target_speed, current_speed + accel)
    else:
        new_speed = max(target_speed, current_speed - accel)

    # 4. Set velocity in heading direction
    direction = Vector2.from_angle(tank.heading)
    tank.velocity = direction * new_speed

    # 5. Compute new position
    new_pos = tank.position + tank.velocity * dt

    # 6. Wall collision — revert to old position if not passable
    if not arena.is_passable(new_pos):
        # Try sliding along each axis independently
        slide_x = Vector2(new_pos.x, tank.position.y)
        slide_y = Vector2(tank.position.x, new_pos.y)
        if arena.is_passable(slide_x):
            new_pos = slide_x
        elif arena.is_passable(slide_y):
            new_pos = slide_y
        else:
            new_pos = tank.position
            tank.velocity = Vector2(0.0, 0.0)

    # 7. Tank-tank collision — push apart
    for other in all_tanks:
        if other.id == tank.id or not other.is_alive:
            continue
        diff = new_pos - other.position
        dist = diff.length()
        min_dist = TANK_RADIUS * 2
        if dist < min_dist and dist > 1e-6:
            # Push this tank away from other
            push = diff.normalized() * (min_dist - dist)
            new_pos = new_pos + push
            tank.velocity = Vector2(0.0, 0.0)

    # 8. Clamp to arena bounds
    margin = TANK_RADIUS
    new_pos = Vector2(
        max(margin, min(arena.width - margin, new_pos.x)),
        max(margin, min(arena.height - margin, new_pos.y)),
    )

    tank.position = new_pos


def _probe_clear(pos: Vector2, heading: float, arena: Arena) -> float:
    """Return a clearance score (0.0–1.0) for a heading from a position.

    Checks multiple distances ahead. Score is the fraction of probe
    distances that are passable — higher means more room ahead.
    """
    direction = Vector2.from_angle(heading)
    clear = 0
    for dist in WALL_PROBE_DISTANCES:
        if arena.is_passable(pos + direction * dist):
            clear += 1
        else:
            break  # If near probe blocked, far ones don't help
    return clear / len(WALL_PROBE_DISTANCES)


def compute_wall_avoidance(tank: Tank, desired_heading: float, arena: Arena) -> float:
    """Adjust desired heading to avoid walls.

    Uses multi-distance probes to score directions. If the desired
    direction is fully clear, returns it unchanged. Otherwise picks the
    alternative heading closest to desired that has maximum clearance.
    """
    # Fast path: desired direction fully clear at all distances
    desired_score = _probe_clear(tank.position, desired_heading, arena)
    if desired_score >= 1.0:
        return desired_heading

    # Desired direction is at least partially blocked — evaluate alternatives
    best_heading = desired_heading
    best_score = desired_score
    best_offset = 360.0

    for offset in WALL_AVOIDANCE_OFFSETS:
        test_heading = (desired_heading + offset) % 360
        score = _probe_clear(tank.position, test_heading, arena)
        abs_offset = abs(offset)
        # Prefer: higher clearance score, then smaller offset from desired
        if score > best_score or (score == best_score and abs_offset < best_offset):
            best_score = score
            best_heading = test_heading
            best_offset = abs_offset

    if best_score > 0:
        return best_heading

    # Everything blocked — reverse
    return (desired_heading + 180) % 360


def update_turret(tank: Tank, desired_turret_angle: float, dt: float) -> None:
    """Rotate turret toward desired angle, clamped by rotation speed."""
    if not tank.is_alive:
        return
    if tank.is_repairing:
        return  # Can't rotate turret while repairing
    delta = tank.desired_turret_delta(desired_turret_angle, dt)
    tank.turret_angle = (tank.turret_angle + delta) % 360
