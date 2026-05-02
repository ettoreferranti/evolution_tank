"""Tests for fitness evaluation."""

from __future__ import annotations

import pytest

from evolution_tank.config import Config, FitnessConfig, FitnessWeights
from evolution_tank.evolution.fitness import compute_average_fitness, compute_fitness
from evolution_tank.simulation.match import MatchResult, TeamResult


def _weights(**overrides) -> FitnessConfig:
    defaults = dict(
        win=10.0, damage_dealt=1.0, friendly_fire=-2.0, damage_taken=-0.5,
        survival_time=0.1, ammo_efficiency=2.0, team_coordination=1.0,
    )
    defaults.update(overrides)
    return FitnessConfig(weights=FitnessWeights(**defaults))


def _team_result(team_id: int = 0, won: bool = False, **kwargs) -> TeamResult:
    defaults = dict(
        team_id=team_id,
        tanks_alive=3,
        total_damage_dealt=100.0,
        total_friendly_damage=0.0,
        total_damage_taken=50.0,
        total_kills=2,
        total_shots_fired=20,
        total_shots_hit=10,
        total_survival_ticks=3000,
        total_signals_sent=5,
        won=won,
    )
    defaults.update(kwargs)
    return TeamResult(**defaults)


def _match_result(team_results: list[TeamResult],
                  winning_team_id: int | None = None) -> MatchResult:
    return MatchResult(
        winning_team_id=winning_team_id,
        team_results=team_results,
        total_ticks=6000,
        timed_out=False,
    )


class TestComputeFitness:
    def test_win_bonus(self):
        cfg = _weights()
        winner = _team_result(won=True)
        loser = _team_result(won=False)
        mr = _match_result([winner, loser], winning_team_id=0)

        score_w = compute_fitness(winner, mr, cfg)
        score_l = compute_fitness(loser, mr, cfg)
        assert score_w - score_l == pytest.approx(10.0)

    def test_damage_components(self):
        cfg = _weights(win=0, survival_time=0, ammo_efficiency=0, team_coordination=0,
                       friendly_fire=0)
        tr = _team_result(total_damage_dealt=200.0, total_damage_taken=100.0)
        mr = _match_result([tr])
        score = compute_fitness(tr, mr, cfg)
        # 1.0 * 200 + (-0.5) * 100 = 150
        assert score == pytest.approx(150.0)

    def test_friendly_fire_penalty(self):
        cfg = _weights(win=0, damage_dealt=0, damage_taken=0,
                       survival_time=0, ammo_efficiency=0, team_coordination=0)
        tr_no_ff = _team_result(total_friendly_damage=0.0)
        tr_ff = _team_result(total_friendly_damage=100.0)
        mr = _match_result([tr_no_ff])
        score_clean = compute_fitness(tr_no_ff, mr, cfg)
        score_ff = compute_fitness(tr_ff, mr, cfg)
        # -2.0 * 100 = -200 penalty
        assert score_ff < score_clean
        assert score_clean - score_ff == pytest.approx(200.0)

    def test_ammo_efficiency(self):
        cfg = _weights(win=0, damage_dealt=0, damage_taken=0,
                       survival_time=0, team_coordination=0)
        # 10 hits / 20 shots = 0.5 efficiency
        tr = _team_result(total_shots_fired=20, total_shots_hit=10)
        mr = _match_result([tr])
        score = compute_fitness(tr, mr, cfg)
        assert score == pytest.approx(2.0 * 0.5)

    def test_ammo_efficiency_zero_shots(self):
        cfg = _weights(win=0, damage_dealt=0, damage_taken=0,
                       survival_time=0, team_coordination=0)
        tr = _team_result(total_shots_fired=0, total_shots_hit=0)
        mr = _match_result([tr])
        score = compute_fitness(tr, mr, cfg)
        assert score == pytest.approx(0.0)

    def test_survival_time(self):
        cfg = _weights(win=0, damage_dealt=0, damage_taken=0,
                       ammo_efficiency=0, team_coordination=0)
        tr = _team_result(total_survival_ticks=6000, total_kills=2)
        mr = _match_result([tr])
        score = compute_fitness(tr, mr, cfg)
        # survival is proportional to kills: 0.1 * 6000 * 2
        assert score == pytest.approx(0.1 * 6000 * 2)

    def test_survival_zero_kills_earns_nothing(self):
        cfg = _weights(win=0, damage_dealt=0, damage_taken=0,
                       ammo_efficiency=0, team_coordination=0)
        tr = _team_result(total_survival_ticks=6000, total_kills=0)
        mr = _match_result([tr])
        score = compute_fitness(tr, mr, cfg)
        assert score == pytest.approx(0.0)

    def test_team_coordination(self):
        cfg = _weights(win=0, damage_dealt=0, damage_taken=0,
                       survival_time=0, ammo_efficiency=0)
        tr = _team_result(total_signals_sent=8)
        mr = _match_result([tr])
        score = compute_fitness(tr, mr, cfg)
        assert score == pytest.approx(1.0 * 8)

    def test_all_components_combine(self):
        cfg = _weights()
        tr = _team_result(
            won=True,
            total_damage_dealt=100.0,
            total_friendly_damage=20.0,
            total_damage_taken=50.0,
            total_shots_fired=20,
            total_shots_hit=10,
            total_survival_ticks=3000,
            total_signals_sent=5,
        )
        mr = _match_result([tr], winning_team_id=0)
        score = compute_fitness(tr, mr, cfg)
        expected = (
            10.0              # win
            + 1.0 * 100.0     # damage dealt
            + (-2.0) * 20.0   # friendly fire
            + (-0.5) * 50.0   # damage taken
            + 0.1 * 3000 * 2  # survival (proportional to kills=2)
            + 2.0 * 0.5       # ammo efficiency
            + 1.0 * 5         # coordination
        )
        assert score == pytest.approx(expected)

    def test_higher_damage_dealt_better(self):
        cfg = _weights()
        low = _team_result(total_damage_dealt=50.0)
        high = _team_result(total_damage_dealt=200.0)
        mr = _match_result([low])
        score_low = compute_fitness(low, mr, cfg)
        score_high = compute_fitness(high, mr, cfg)
        assert score_high > score_low

    def test_uses_config_weights(self):
        """Fitness from real config file should work."""
        config = Config.load("config/settings.yaml")
        tr = _team_result(won=True, total_damage_dealt=500.0)
        mr = _match_result([tr], winning_team_id=0)
        score = compute_fitness(tr, mr, config.fitness)
        assert score > 0


class TestComputeAverageFitness:
    def test_averages_multiple_matches(self):
        cfg = _weights(win=10, damage_dealt=0, damage_taken=0,
                       survival_time=0, ammo_efficiency=0, team_coordination=0)
        # Win one, lose one
        tr_win = _team_result(team_id=0, won=True)
        tr_lose = _team_result(team_id=0, won=False)
        tr_opp1 = _team_result(team_id=1, won=False)
        tr_opp2 = _team_result(team_id=1, won=True)

        results = [
            _match_result([tr_win, tr_opp1], winning_team_id=0),
            _match_result([tr_lose, tr_opp2], winning_team_id=1),
        ]
        avg = compute_average_fitness(0, results, cfg)
        assert avg == pytest.approx(5.0)  # (10 + 0) / 2

    def test_empty_results(self):
        cfg = _weights()
        assert compute_average_fitness(0, [], cfg) == 0.0

    def test_team_not_found(self):
        cfg = _weights()
        tr = _team_result(team_id=1)
        results = [_match_result([tr])]
        assert compute_average_fitness(0, results, cfg) == 0.0
