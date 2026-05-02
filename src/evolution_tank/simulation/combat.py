"""Combat system — projectile management, hit detection, damage."""

from __future__ import annotations

from evolution_tank.simulation.arena import Arena, Vector2
from evolution_tank.tanks.tank import Projectile, Tank

# Projectile hit radius
PROJECTILE_RADIUS = 3.0
TANK_HIT_RADIUS = 8.0


def update_projectiles(
    projectiles: list[Projectile],
    arena: Arena,
    tanks: list[Tank],
    dt: float,
    friendly_fire: bool,
) -> list[Projectile]:
    """Advance projectiles and check hits. Returns list of still-active projectiles."""
    surviving: list[Projectile] = []

    for proj in projectiles:
        if not proj.active:
            continue

        # Move projectile
        old_pos = proj.position
        proj.update(dt)

        if not proj.active:
            continue

        # Wall collision — check along path
        if _ray_hits_wall(old_pos, proj.position, arena):
            proj.active = False
            continue

        # Tank hit detection
        hit_tank = _find_hit_tank(proj, tanks, friendly_fire)
        if hit_tank is not None:
            actual_damage = hit_tank.take_damage(proj.damage)
            # Credit the shooter
            shooter = _find_tank_by_id(tanks, proj.owner_id)
            if shooter is not None:
                is_friendly = shooter.team_id == hit_tank.team_id
                shooter.record_hit()
                shooter.record_damage_dealt(actual_damage, friendly=is_friendly)
                if not hit_tank.is_alive and not is_friendly:
                    shooter.record_kill()
            proj.active = False
            continue

        surviving.append(proj)

    return surviving


def _find_hit_tank(
    proj: Projectile,
    tanks: list[Tank],
    friendly_fire: bool,
) -> Tank | None:
    """Find the closest tank hit by a projectile this tick."""
    hit_radius = PROJECTILE_RADIUS + TANK_HIT_RADIUS
    closest: Tank | None = None
    closest_dist = float("inf")

    for tank in tanks:
        if not tank.is_alive:
            continue
        if tank.id == proj.owner_id:
            continue  # Can't hit yourself
        if not friendly_fire and tank.team_id == proj.team_id:
            continue

        dist = proj.position.distance_to(tank.position)
        if dist < hit_radius and dist < closest_dist:
            closest = tank
            closest_dist = dist

    return closest


def _ray_hits_wall(start: Vector2, end: Vector2, arena: Arena) -> bool:
    """Check if a line segment passes through a wall cell.

    Uses simple stepping along the ray.
    """
    diff = end - start
    length = diff.length()
    if length < 1e-6:
        return arena.blocks_los(start)

    step_size = arena.cell_size / 2  # Check at half-cell intervals
    steps = max(1, int(length / step_size))
    for i in range(1, steps + 1):
        t = i / steps
        point = start + diff * t
        if arena.blocks_los(point):
            return True
    return False


def _find_tank_by_id(tanks: list[Tank], tank_id: int) -> Tank | None:
    for t in tanks:
        if t.id == tank_id:
            return t
    return None
