"""Tests for match system and simulation loop."""

import random

import pytest

from evolution_tank.config import Config
from evolution_tank.simulation.arena import Vector2, load_preset
from evolution_tank.simulation.fog_of_war import SensorSnapshot
from evolution_tank.simulation.match import (
    MatchResult,
    TankCommand,
    run_match,
    run_best_of_n,
)
from evolution_tank.tanks.tank import Tank, TankType


@pytest.fixture
def config():
    return Config.load()


def _make_teams(config, arena, team_sizes: list[int], rng: random.Random) -> list[Tank]:
    """Create tanks for multiple teams with spawn positions."""
    positions = arena.compute_spawn_positions(
        len(team_sizes), max(team_sizes), config.match.spawn, rng,
    )
    tanks = []
    tank_id = 0
    center = Vector2(arena.width / 2, arena.height / 2)
    for team_id, size in enumerate(team_sizes):
        for i in range(size):
            pos = positions[team_id][i]
            heading = (center - pos).angle()
            t = Tank(
                id=tank_id, team_id=team_id, tank_type=TankType.MEDIUM,
                type_config=config.tank_types["medium"],
                position=pos, heading=heading,
            )
            tanks.append(t)
            tank_id += 1
    return tanks


def _idle_strategy(tank: Tank, sensor: SensorSnapshot) -> TankCommand:
    return TankCommand()


def _aggressive_strategy(tank: Tank, sensor: SensorSnapshot) -> TankCommand:
    cmd = TankCommand()
    if sensor.visible_enemies:
        nearest = min(sensor.visible_enemies, key=lambda e: e.distance)
        diff = nearest.position - tank.position
        cmd.desired_heading = diff.angle()
        cmd.desired_speed = 1.0
        lead = Tank.compute_lead_angle(
            tank.position, nearest.position, nearest.velocity,
            tank.type_config.projectile_speed,
        )
        cmd.desired_turret_angle = lead if lead is not None else diff.angle()
        cmd.fire = True
    else:
        center = Vector2(400, 400)
        cmd.desired_heading = (center - tank.position).angle()
        cmd.desired_speed = 1.0
        cmd.desired_turret_angle = cmd.desired_heading
    return cmd


class TestMatchCompletion:
    def test_match_runs_to_completion(self, config):
        arena = load_preset("open")
        rng = random.Random(42)
        tanks = _make_teams(config, arena, [3, 3], rng)
        strategies = {t.id: _aggressive_strategy for t in tanks}
        result = run_match(config, arena, tanks, strategies)
        assert isinstance(result, MatchResult)
        assert result.total_ticks > 0

    def test_match_produces_winner_or_draw(self, config):
        arena = load_preset("open")
        rng = random.Random(42)
        tanks = _make_teams(config, arena, [3, 3], rng)
        strategies = {t.id: _aggressive_strategy for t in tanks}
        result = run_match(config, arena, tanks, strategies)
        # Winner is either a team ID or None (draw)
        assert result.winning_team_id is None or result.winning_team_id in [0, 1]


class TestWinConditions:
    def test_last_team_standing(self, config):
        arena = load_preset("open")
        rng = random.Random(42)
        tanks = _make_teams(config, arena, [3, 3], rng)
        # One team aggressive, other idle
        strategies = {}
        for t in tanks:
            if t.team_id == 0:
                strategies[t.id] = _aggressive_strategy
            else:
                strategies[t.id] = _idle_strategy
        result = run_match(config, arena, tanks, strategies)
        # Aggressive team should eventually win
        assert result.winning_team_id == 0 or result.timed_out

    def test_time_limit(self, config):
        arena = load_preset("open")
        rng = random.Random(42)
        tanks = _make_teams(config, arena, [1, 1], rng)
        # Both idle — match should time out
        strategies = {t.id: _idle_strategy for t in tanks}
        result = run_match(config, arena, tanks, strategies)
        assert result.timed_out
        assert result.total_ticks == config.match.max_ticks

    def test_tiebreaker_most_damage(self, config):
        arena = load_preset("open")
        rng = random.Random(42)
        tanks = _make_teams(config, arena, [1, 1], rng)
        # Both idle → no damage → should be a draw
        strategies = {t.id: _idle_strategy for t in tanks}
        result = run_match(config, arena, tanks, strategies)
        assert result.timed_out
        # Both dealt 0 damage → draw
        assert result.winning_team_id is None


class TestMatchResults:
    def test_team_results_populated(self, config):
        arena = load_preset("open")
        rng = random.Random(42)
        tanks = _make_teams(config, arena, [3, 3], rng)
        strategies = {t.id: _aggressive_strategy for t in tanks}
        result = run_match(config, arena, tanks, strategies)
        assert len(result.team_results) == 2
        for tr in result.team_results:
            assert tr.total_survival_ticks > 0

    def test_damage_recorded(self, config):
        arena = load_preset("open")
        rng = random.Random(42)
        tanks = _make_teams(config, arena, [3, 3], rng)
        strategies = {t.id: _aggressive_strategy for t in tanks}
        result = run_match(config, arena, tanks, strategies)
        total_damage = sum(tr.total_damage_dealt for tr in result.team_results)
        assert total_damage > 0

    def test_winner_flag_set(self, config):
        arena = load_preset("open")
        rng = random.Random(42)
        tanks = _make_teams(config, arena, [3, 3], rng)
        strategies = {t.id: _aggressive_strategy for t in tanks}
        result = run_match(config, arena, tanks, strategies)
        if result.winning_team_id is not None:
            winners = [tr for tr in result.team_results if tr.won]
            assert len(winners) == 1
            assert winners[0].team_id == result.winning_team_id


class TestBestOfN:
    def test_best_of_n_returns_n_results(self, config):
        arena = load_preset("open")
        rng = random.Random(42)

        def create_tanks():
            return _make_teams(config, arena, [2, 2], rng)

        tanks = create_tanks()
        strategies = {t.id: _aggressive_strategy for t in tanks}
        results = run_best_of_n(config, arena, create_tanks, strategies, 3)
        assert len(results) == 3


class TestFreeForAll:
    def test_free_for_all_each_tank_own_team(self, config):
        arena = load_preset("open")
        tanks = [
            Tank(id=i, team_id=i, tank_type=TankType.MEDIUM,
                 type_config=config.tank_types["medium"],
                 position=Vector2(100 + i * 50, 400))
            for i in range(4)
        ]
        strategies = {t.id: _aggressive_strategy for t in tanks}
        result = run_match(config, arena, tanks, strategies)
        assert len(result.team_results) == 4


class TestDeterminism:
    def test_same_seed_same_result(self, config):
        arena = load_preset("open")

        def run_with_seed(seed):
            rng = random.Random(seed)
            tanks = _make_teams(config, arena, [3, 3], rng)
            strategies = {t.id: _aggressive_strategy for t in tanks}
            return run_match(config, arena, tanks, strategies)

        r1 = run_with_seed(42)
        r2 = run_with_seed(42)
        assert r1.winning_team_id == r2.winning_team_id
        assert r1.total_ticks == r2.total_ticks

    def test_different_seed_may_differ(self, config):
        arena = load_preset("open")
        results = []
        for seed in [1, 2, 3, 4, 5]:
            rng = random.Random(seed)
            tanks = _make_teams(config, arena, [3, 3], rng)
            strategies = {t.id: _aggressive_strategy for t in tanks}
            r = run_match(config, arena, tanks, strategies)
            results.append(r.total_ticks)
        # Not all results should be identical (extremely unlikely)
        assert len(set(results)) > 1
