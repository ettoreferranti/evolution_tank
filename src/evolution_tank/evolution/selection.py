"""Selection operators — tournament selection, next-generation assembly."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from evolution_tank.evolution.mutation import (
    crossover,
    mutate_composition,
    mutate_parameters,
    mutate_structure,
)
from evolution_tank.strategy.behavior_tree import BehaviorTree
from evolution_tank.strategy.serialization import deserialize_tree, serialize_tree

if TYPE_CHECKING:
    from evolution_tank.config import EvolutionConfig


def tournament_select(
    population: list[BehaviorTree],
    fitnesses: list[float],
    tournament_size: int,
    rng: random.Random,
) -> BehaviorTree:
    """Select one individual via tournament selection.

    Picks tournament_size random individuals, returns the one with
    highest fitness. Returns a deep copy.
    """
    indices = rng.sample(range(len(population)), min(tournament_size, len(population)))
    best_idx = max(indices, key=lambda i: fitnesses[i])
    # Deep copy via serialization
    return deserialize_tree(serialize_tree(population[best_idx]))


def select_next_generation(
    population: list[BehaviorTree],
    fitnesses: list[float],
    config: EvolutionConfig,
    rng: random.Random,
) -> list[BehaviorTree]:
    """Build the next generation from the current population.

    Steps:
        1. Elitism — preserve top-K unchanged.
        2. Fill remaining slots via tournament selection.
        3. Apply crossover with probability crossover_rate.
        4. Apply parameter mutation to all non-elite individuals.
    """
    pop_size = config.population_size
    elitism_count = min(config.elitism_count, len(population))

    # 1. Elitism — take top-K by fitness
    ranked = sorted(range(len(population)), key=lambda i: fitnesses[i], reverse=True)
    next_gen: list[BehaviorTree] = []
    for i in range(elitism_count):
        elite = deserialize_tree(serialize_tree(population[ranked[i]]))
        next_gen.append(elite)

    # 2. Fill remaining slots
    remaining = pop_size - elitism_count
    selected: list[BehaviorTree] = []
    for _ in range(remaining):
        selected.append(tournament_select(
            population, fitnesses, config.tournament_size, rng,
        ))

    # 3. Crossover — pair up selected individuals
    offspring: list[BehaviorTree] = []
    i = 0
    while i < len(selected):
        if i + 1 < len(selected) and rng.random() < config.crossover_rate:
            child_a, child_b = crossover(
                selected[i], selected[i + 1],
                config.max_tree_depth, rng,
            )
            offspring.append(child_a)
            offspring.append(child_b)
            i += 2
        else:
            offspring.append(selected[i])
            i += 1

    # Trim to exact size needed
    offspring = offspring[:remaining]

    # 4. Mutation on all offspring (not elites)
    for j in range(len(offspring)):
        offspring[j] = mutate_parameters(offspring[j], config.mutation, rng)
        offspring[j] = mutate_structure(offspring[j], config.mutation, config.max_tree_depth, rng)
        if config.composition.enabled:
            offspring[j] = mutate_composition(offspring[j], rng, config.mutation.parameter_rate)

    next_gen.extend(offspring)
    return next_gen
