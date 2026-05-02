"""Match system — runs a complete battle between teams."""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from evolution_tank.simulation.arena import Arena, Vector2
from evolution_tank.simulation.combat import update_projectiles
from evolution_tank.simulation.fog_of_war import SensorSnapshot, compute_sensor_data
from evolution_tank.simulation.physics import update_tank_movement, update_turret
from evolution_tank.tanks.tank import Projectile, Tank, TankState

if TYPE_CHECKING:
    from evolution_tank.config import Config


# ---------------------------------------------------------------------------
# Tank commands — output of the strategy decision phase
# ---------------------------------------------------------------------------

@dataclass
class TankCommand:
    """Commands issued by a strategy for one tick."""
    desired_heading: float | None = None   # None = keep current
    desired_speed: float = 0.0             # 0.0–1.0
    desired_turret_angle: float = 0.0
    fire: bool = False
    repair: bool = False
    signal_type: str | None = None         # e.g. "ENEMY_SPOTTED"
    signal_position: Vector2 | None = None


# Strategy callback type: takes (tank, sensor_data) → TankCommand
StrategyFn = Callable[[Tank, SensorSnapshot], TankCommand]


# ---------------------------------------------------------------------------
# Match result
# ---------------------------------------------------------------------------

@dataclass
class TeamResult:
    team_id: int
    tanks_alive: int
    total_damage_dealt: float       # damage to enemies only
    total_friendly_damage: float    # damage to own team
    total_damage_taken: float
    total_kills: int
    total_shots_fired: int
    total_shots_hit: int
    total_survival_ticks: int
    total_signals_sent: int
    won: bool


@dataclass
class MatchResult:
    winning_team_id: int | None  # None = draw
    team_results: list[TeamResult]
    total_ticks: int
    timed_out: bool


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    signal_type: str
    position: Vector2
    sender_id: int
    team_id: int
    tick: int


# ---------------------------------------------------------------------------
# Match state — the full state of a running battle
# ---------------------------------------------------------------------------

@dataclass
class MatchState:
    """Holds the complete mutable state of a match in progress."""
    tanks: list[Tank]
    projectiles: list[Projectile] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    tick: int = 0
    recently_hit_ids: set[int] = field(default_factory=set)
    finished: bool = False
    result: MatchResult | None = None


# ---------------------------------------------------------------------------
# Tick callback for visualization
# ---------------------------------------------------------------------------

TickCallback = Callable[[MatchState, Arena], None]


# ---------------------------------------------------------------------------
# Match runner
# ---------------------------------------------------------------------------

def run_match(
    config: Config,
    arena: Arena,
    tanks: list[Tank],
    strategies: dict[int, StrategyFn],
    tick_callback: TickCallback | None = None,
) -> MatchResult:
    """Run a single match to completion.

    Args:
        config: Full configuration.
        arena: The arena to fight in.
        tanks: List of all tanks (already positioned).
        strategies: Map from tank.id → strategy function.
        tick_callback: Optional function called each tick (for visualization).

    Returns:
        MatchResult with outcome.
    """
    dt = 1.0 / config.match.ticks_per_second
    max_ticks = config.match.max_ticks if config.match.max_ticks > 0 else float("inf")

    state = MatchState(tanks=tanks)

    while not state.finished:
        _run_tick(config, arena, state, strategies, dt)

        if tick_callback is not None:
            tick_callback(state, arena)

        # Check win condition
        result = _check_win_condition(state, config, max_ticks)
        if result is not None:
            state.finished = True
            state.result = result

    return state.result


def _run_tick(
    config: Config,
    arena: Arena,
    state: MatchState,
    strategies: dict[int, StrategyFn],
    dt: float,
) -> None:
    """Execute one simulation tick."""
    state.tick += 1
    new_hit_ids: set[int] = set()

    # Phase 1: Sense — compute sensor data for each living tank
    sensor_data: dict[int, SensorSnapshot] = {}
    for tank in state.tanks:
        if tank.is_alive:
            sensor_data[tank.id] = compute_sensor_data(
                tank, state.tanks, arena, config.fog_of_war, state.recently_hit_ids,
                signals=state.signals,
            )

    # Phase 2: Decide — evaluate strategy for each living tank
    commands: dict[int, TankCommand] = {}
    for tank in state.tanks:
        if not tank.is_alive:
            continue
        strategy = strategies.get(tank.id)
        if strategy is not None and tank.id in sensor_data:
            commands[tank.id] = strategy(tank, sensor_data[tank.id])
        else:
            commands[tank.id] = TankCommand()  # idle

    # Phase 3: Act — apply commands
    new_projectiles: list[Projectile] = []

    for tank in state.tanks:
        if not tank.is_alive:
            continue

        cmd = commands.get(tank.id, TankCommand())

        # Handle repair command (only if active and not already repairing)
        if cmd.repair and tank.can_repair:
            tank.start_repair()

        # Movement (no movement if repairing)
        if tank.is_active:
            update_tank_movement(
                tank, cmd.desired_heading, cmd.desired_speed,
                arena, config.arena, dt, state.tanks,
            )
            update_turret(tank, cmd.desired_turret_angle, dt)

        # Firing
        if cmd.fire and tank.can_fire:
            proj = tank.fire()
            if proj is not None:
                new_projectiles.append(proj)

        # Signals
        if cmd.signal_type and config.communication.enabled:
            signal_pos = cmd.signal_position or tank.position
            state.signals.append(Signal(
                signal_type=cmd.signal_type,
                position=signal_pos,
                sender_id=tank.id,
                team_id=tank.team_id,
                tick=state.tick,
            ))
            tank.signals_sent += 1

    state.projectiles.extend(new_projectiles)

    # Phase 4: Physics — update projectiles, detect hits
    # Track HP before to detect who got hit this tick
    hp_before = {t.id: t.hp for t in state.tanks if t.is_alive}

    state.projectiles = update_projectiles(
        state.projectiles, arena, state.tanks, dt, config.combat.friendly_fire,
    )

    # Detect who was hit this tick
    for tank in state.tanks:
        if tank.id in hp_before and tank.hp < hp_before[tank.id]:
            new_hit_ids.add(tank.id)

    state.recently_hit_ids = new_hit_ids

    # Phase 5: Update timers
    for tank in state.tanks:
        tank.update_timers(dt)

    # Clean up old signals (keep last 60 ticks worth)
    cutoff = state.tick - 60
    state.signals = [s for s in state.signals if s.tick > cutoff]


def _check_win_condition(
    state: MatchState,
    config: Config,
    max_ticks: int | float,
) -> MatchResult | None:
    """Check if match should end. Returns result or None if ongoing."""
    # Gather living teams
    teams_alive: set[int] = set()
    for tank in state.tanks:
        if tank.is_alive:
            teams_alive.add(tank.team_id)

    timed_out = state.tick >= max_ticks

    # Last team standing
    if len(teams_alive) <= 1 or timed_out:
        return _build_result(state, teams_alive, timed_out)

    return None


def _build_result(
    state: MatchState,
    teams_alive: set[int],
    timed_out: bool,
) -> MatchResult:
    """Build the match result."""
    # Gather all team IDs
    all_team_ids: set[int] = set()
    for tank in state.tanks:
        all_team_ids.add(tank.team_id)

    team_results: list[TeamResult] = []
    for team_id in sorted(all_team_ids):
        team_tanks = [t for t in state.tanks if t.team_id == team_id]
        team_results.append(TeamResult(
            team_id=team_id,
            tanks_alive=sum(1 for t in team_tanks if t.is_alive),
            total_damage_dealt=sum(t.damage_dealt for t in team_tanks),
            total_friendly_damage=sum(t.friendly_damage_dealt for t in team_tanks),
            total_damage_taken=sum(t.damage_taken for t in team_tanks),
            total_kills=sum(t.kills for t in team_tanks),
            total_shots_fired=sum(t.shots_fired for t in team_tanks),
            total_shots_hit=sum(t.shots_hit for t in team_tanks),
            total_survival_ticks=sum(t.survival_ticks for t in team_tanks),
            total_signals_sent=sum(t.signals_sent for t in team_tanks),
            won=False,
        ))

    # Determine winner
    winning_team_id: int | None = None
    if len(teams_alive) == 1:
        winning_team_id = next(iter(teams_alive))
    elif len(teams_alive) == 0:
        # Mutual destruction — nobody wins
        winning_team_id = None
    elif timed_out:
        # Tiebreaker: most damage dealt
        best = max(team_results, key=lambda r: r.total_damage_dealt)
        # Check for actual tie
        top_damage = best.total_damage_dealt
        top_teams = [r for r in team_results if r.total_damage_dealt == top_damage]
        if len(top_teams) == 1:
            winning_team_id = best.team_id
        else:
            winning_team_id = None  # True tie

    # Mark winner
    for tr in team_results:
        tr.won = (tr.team_id == winning_team_id)

    return MatchResult(
        winning_team_id=winning_team_id,
        team_results=team_results,
        total_ticks=state.tick,
        timed_out=timed_out,
    )


def run_best_of_n(
    config: Config,
    arena: Arena,
    create_tanks_fn: Callable[[], list[Tank]],
    strategies: dict[int, StrategyFn],
    n: int,
    tick_callback: TickCallback | None = None,
) -> list[MatchResult]:
    """Run a best-of-N series. Returns all match results."""
    results: list[MatchResult] = []
    for _ in range(n):
        tanks = create_tanks_fn()
        # Re-map strategies to new tank IDs if needed
        result = run_match(config, arena, tanks, strategies, tick_callback)
        results.append(result)
    return results
