"""Fitness evaluation — scores a strategy's performance from match results."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evolution_tank.config import FitnessConfig
    from evolution_tank.simulation.match import MatchResult, TeamResult


def compute_fitness(
    team_result: TeamResult,
    match_result: MatchResult,
    fitness_config: FitnessConfig,
) -> float:
    """Compute a fitness score for a team's performance in one match.

    Components (all weighted by fitness_config.weights):
        - win: Flat bonus for winning.
        - damage_dealt: Total damage dealt.
        - damage_taken: Penalty for damage taken (weight is typically negative).
        - survival_time: Average survival ticks per tank, normalized to seconds.
        - ammo_efficiency: Hit/shot ratio (0 if no shots fired).
        - team_coordination: Bonus for signal usage.
    """
    w = fitness_config.weights

    # Win/loss
    win_score = w.win if team_result.won else 0.0

    # Damage — enemy damage is positive, friendly fire is penalized
    damage_score = w.damage_dealt * team_result.total_damage_dealt
    friendly_fire_score = w.friendly_fire * team_result.total_friendly_damage
    taken_score = w.damage_taken * team_result.total_damage_taken

    # Survival — proportional to enemy kills so passive survival earns nothing
    survival_score = w.survival_time * team_result.total_survival_ticks * team_result.total_kills

    # Ammo efficiency — shots hit / shots fired
    if team_result.total_shots_fired > 0:
        efficiency = team_result.total_shots_hit / team_result.total_shots_fired
    else:
        efficiency = 0.0
    efficiency_score = w.ammo_efficiency * efficiency

    # Team coordination — reward signal usage
    coordination_score = w.team_coordination * team_result.total_signals_sent

    return (
        win_score
        + damage_score
        + friendly_fire_score
        + taken_score
        + survival_score
        + efficiency_score
        + coordination_score
    )


def compute_average_fitness(
    team_id: int,
    match_results: list[MatchResult],
    fitness_config: FitnessConfig,
) -> float:
    """Compute average fitness across multiple matches for one team.

    Each strategy plays multiple opponents per generation. The fitness
    is averaged for robustness against lucky/unlucky pairings.
    """
    if not match_results:
        return 0.0

    total = 0.0
    count = 0
    for result in match_results:
        for tr in result.team_results:
            if tr.team_id == team_id:
                total += compute_fitness(tr, result, fitness_config)
                count += 1
                break

    return total / count if count > 0 else 0.0
