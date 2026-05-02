"""Demo — watch a battle between two simple strategies."""

from __future__ import annotations

import random
import sys

import pygame

from evolution_tank.config import Config
from evolution_tank.simulation.arena import Arena, Vector2, load_preset
from evolution_tank.simulation.fog_of_war import SensorSnapshot
from evolution_tank.simulation.match import MatchState, TankCommand, run_match
from evolution_tank.simulation.physics import compute_wall_avoidance
from evolution_tank.tanks.tank import Tank, TankType
from evolution_tank.visualization.renderer import BattleRenderer

# Global ref to arena so strategies can use wall avoidance
_demo_arena: Arena | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _avoid_walls(tank: Tank, heading: float) -> float:
    """Adjust heading to steer around walls."""
    if _demo_arena is not None:
        return compute_wall_avoidance(tank, heading, _demo_arena)
    return heading


# ---------------------------------------------------------------------------
# Sample strategies
# ---------------------------------------------------------------------------

def strategy_aggressive(tank: Tank, sensor: SensorSnapshot) -> TankCommand:
    """Rush toward enemies, shoot on sight."""
    cmd = TankCommand()
    center = Vector2(400, 400)

    if sensor.visible_enemies:
        nearest = min(sensor.visible_enemies, key=lambda e: e.distance)
        diff = nearest.position - tank.position
        cmd.desired_heading = _avoid_walls(tank, diff.angle())
        cmd.desired_speed = 0.8 if nearest.distance > 60 else 0.3

        lead = Tank.compute_lead_angle(
            tank.position, nearest.position, nearest.velocity,
            tank.type_config.projectile_speed,
        )
        cmd.desired_turret_angle = lead if lead is not None else diff.angle()
        cmd.fire = True

        # Repair if very low
        if tank.hp < tank.max_hp * 0.2 and not sensor.under_fire:
            cmd.repair = True
            cmd.fire = False
    else:
        # Move toward center to find enemies
        cmd.desired_heading = _avoid_walls(tank, (center - tank.position).angle())
        cmd.desired_speed = 1.0
        cmd.desired_turret_angle = (center - tank.position).angle()

    return cmd


def strategy_cautious(tank: Tank, sensor: SensorSnapshot) -> TankCommand:
    """Keep distance, prioritize survival, repair when safe."""
    cmd = TankCommand()
    center = Vector2(400, 400)

    if sensor.visible_enemies:
        nearest = min(sensor.visible_enemies, key=lambda e: e.distance)
        diff = nearest.position - tank.position

        if nearest.distance < 120:
            # Too close — back away
            cmd.desired_heading = _avoid_walls(tank, (tank.position - nearest.position).angle())
            cmd.desired_speed = 1.0
        else:
            # Circle strafe
            perp = Vector2(-diff.normalized().y, diff.normalized().x)
            raw_heading = (diff.normalized() * 0.3 + perp * 0.7).angle()
            cmd.desired_heading = _avoid_walls(tank, raw_heading)
            cmd.desired_speed = 0.7

        lead = Tank.compute_lead_angle(
            tank.position, nearest.position, nearest.velocity,
            tank.type_config.projectile_speed,
        )
        cmd.desired_turret_angle = lead if lead is not None else diff.angle()
        cmd.fire = nearest.distance < tank.type_config.projectile_range * 0.7

        # Repair if damaged and no immediate threat
        if tank.hp < tank.max_hp * 0.4 and nearest.distance > 150:
            cmd.repair = True
            cmd.fire = False
    else:
        # Patrol toward center slowly
        cmd.desired_heading = _avoid_walls(tank, (center - tank.position).angle())
        cmd.desired_speed = 0.6
        cmd.desired_turret_angle = (center - tank.position).angle()

        # Repair if damaged and safe
        if tank.hp < tank.max_hp * 0.6:
            cmd.repair = True

    return cmd


def strategy_sniper(tank: Tank, sensor: SensorSnapshot) -> TankCommand:
    """Stay still, focus on accuracy at range."""
    cmd = TankCommand()
    center = Vector2(400, 400)

    if sensor.visible_enemies:
        # Pick the enemy most worth shooting (furthest that's still in range)
        in_range = [e for e in sensor.visible_enemies
                    if e.distance < tank.type_config.projectile_range * 0.9]
        if in_range:
            target = max(in_range, key=lambda e: e.distance)
        else:
            target = min(sensor.visible_enemies, key=lambda e: e.distance)

        diff = target.position - tank.position
        lead = Tank.compute_lead_angle(
            tank.position, target.position, target.velocity,
            tank.type_config.projectile_speed,
        )
        cmd.desired_turret_angle = lead if lead is not None else diff.angle()
        cmd.fire = True
        cmd.desired_speed = 0.1  # Almost stationary

        # If enemy too close, retreat
        if target.distance < 80:
            cmd.desired_heading = _avoid_walls(tank, (tank.position - target.position).angle())
            cmd.desired_speed = 1.0
    else:
        cmd.desired_heading = _avoid_walls(tank, (center - tank.position).angle())
        cmd.desired_speed = 0.5
        cmd.desired_turret_angle = (center - tank.position).angle()

    return cmd


STRATEGIES = {
    "aggressive": strategy_aggressive,
    "cautious": strategy_cautious,
    "sniper": strategy_sniper,
}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Watch a tank battle demo")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--map", type=str, default="default", choices=["default", "open", "maze", "corridors"])
    parser.add_argument("--team-size", type=int, default=5)
    parser.add_argument("--team0", type=str, default="aggressive", choices=list(STRATEGIES))
    parser.add_argument("--team1", type=str, default="cautious", choices=list(STRATEGIES))
    parser.add_argument("--mixed", action="store_true", help="Use mixed tank types (light/medium/heavy)")
    args = parser.parse_args()

    config = Config.load("config/settings.yaml")
    config = config.with_seed(args.seed)

    arena = load_preset(args.map)
    global _demo_arena
    _demo_arena = arena
    rng = random.Random(args.seed)

    # Create tanks
    spawn = arena.compute_spawn_positions(2, args.team_size, config.match.spawn, rng)
    center = Vector2(arena.width / 2, arena.height / 2)

    if args.mixed:
        type_cycle = [TankType.LIGHT, TankType.MEDIUM, TankType.HEAVY, TankType.MEDIUM, TankType.LIGHT]
    else:
        type_cycle = [TankType.MEDIUM]

    tanks: list[Tank] = []
    strategies: dict[int, any] = {}
    tank_id = 0

    for team_id in range(2):
        strat_fn = STRATEGIES[args.team0 if team_id == 0 else args.team1]
        for i in range(args.team_size):
            pos = spawn[team_id][i]
            heading = (center - pos).angle()
            tt = type_cycle[i % len(type_cycle)]
            t = Tank(
                id=tank_id, team_id=team_id, tank_type=tt,
                type_config=config.tank_types[tt.value],
                position=pos, heading=heading, turret_angle=heading,
            )
            tanks.append(t)
            strategies[tank_id] = strat_fn
            tank_id += 1

    # Set up renderer
    renderer = BattleRenderer(config, arena)

    # Track whether we should skip ticks for speed
    running = True
    ticks_to_skip = 0

    def tick_callback(state: MatchState, arena_ref: any) -> None:
        nonlocal running, ticks_to_skip
        if not running:
            return

        # Handle speed: at 2x we render every other tick, at 4x every 4th, etc.
        if renderer.speed_multiplier > 1:
            ticks_to_skip += 1
            if ticks_to_skip < renderer.speed_multiplier:
                # Still pump events so we can pause/quit
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    if event.type == pygame.KEYDOWN:
                        renderer._handle_key(event)
                return
            ticks_to_skip = 0

        # Handle pause
        while renderer.paused and running:
            if not renderer.render_tick(state, arena_ref):
                running = False
                return

        if not renderer.render_tick(state, arena_ref):
            running = False

    print(f"Battle: Team 0 ({args.team0}) vs Team 1 ({args.team1})")
    print(f"Map: {args.map}, Team size: {args.team_size}, Seed: {args.seed}")
    print(f"Mixed types: {args.mixed}")
    print()
    print("Controls:")
    print("  Space  — Pause/Resume")
    print("  1-9, 0 — Speed (1x–9x, 0=10x)")
    print("  +/-    — Adjust speed")
    print("  F      — Cycle fog of war")
    print("  Q/Esc  — Quit")
    print()

    result = run_match(config, arena, tanks, strategies, tick_callback)

    if running:
        renderer.show_result(result)
        print(f"Result: {'Team ' + str(result.winning_team_id) + ' wins!' if result.winning_team_id is not None else 'Draw!'}")
        print(f"Duration: {result.total_ticks} ticks, Timed out: {result.timed_out}")
        for tr in result.team_results:
            strat = args.team0 if tr.team_id == 0 else args.team1
            ff = f", ff={tr.total_friendly_damage:.0f}" if tr.total_friendly_damage > 0 else ""
            print(f"  Team {tr.team_id} ({strat}): "
                  f"alive={tr.tanks_alive}, dmg={tr.total_damage_dealt:.0f}{ff}, "
                  f"kills={tr.total_kills}, shots={tr.total_shots_fired}/{tr.total_shots_hit}")

    renderer.close()


if __name__ == "__main__":
    main()
