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
from evolution_tank.strategy.behavior_tree import BehaviorTree, next_lineage_id
from evolution_tank.strategy.serialization import deserialize_tree, serialize_tree

if TYPE_CHECKING:
    from evolution_tank.config import EvolutionConfig


def tournament_select(
    population: list[BehaviorTree],
    fitnesses: list[float],
    tournament_size: int,
    rng: random.Random,
) -> tuple[BehaviorTree, int]:
    """Select one individual via tournament selection.

    Picks tournament_size random individuals, returns the one with
    highest fitness as a deep copy, along with the parent's lineage_id.
    """
    indices = rng.sample(range(len(population)), min(tournament_size, len(population)))
    best_idx = max(indices, key=lambda i: fitnesses[i])
    parent_id = population[best_idx].lineage_id
    copy = deserialize_tree(serialize_tree(population[best_idx]))
    return copy, parent_id


def select_next_generation(
    population: list[BehaviorTree],
    fitnesses: list[float],
    config: EvolutionConfig,
    rng: random.Random,
) -> list[BehaviorTree]:
    """Build the next generation from the current population.

    Steps:
        1. Elitism — preserve top-K unchanged (same lineage_id, no parents).
        2. Fill remaining slots via tournament selection.
        3. Apply crossover with probability crossover_rate.
        4. Apply parameter mutation to all non-elite individuals.

    Each new individual gets a fresh lineage_id and records its parent(s).
    """
    pop_size = config.population_size
    elitism_count = min(config.elitism_count, len(population))

    # 1. Elitism — take top-K by fitness (preserve lineage_id)
    ranked = sorted(range(len(population)), key=lambda i: fitnesses[i], reverse=True)
    next_gen: list[BehaviorTree] = []
    for i in range(elitism_count):
        elite = deserialize_tree(serialize_tree(population[ranked[i]]))
        # Elites keep their lineage_id — they're the same individual carried forward
        next_gen.append(elite)

    # 2. Fill remaining slots — track parent lineage IDs
    remaining = pop_size - elitism_count
    selected: list[BehaviorTree] = []
    parent_ids: list[int] = []
    for _ in range(remaining):
        tree, pid = tournament_select(
            population, fitnesses, config.tournament_size, rng,
        )
        selected.append(tree)
        parent_ids.append(pid)

    # 3. Crossover — pair up selected individuals
    offspring: list[BehaviorTree] = []
    offspring_parents: list[tuple[int, ...]] = []
    i = 0
    while i < len(selected):
        if i + 1 < len(selected) and rng.random() < config.crossover_rate:
            child_a, child_b = crossover(
                selected[i], selected[i + 1],
                config.max_tree_depth, rng,
            )
            offspring.append(child_a)
            offspring.append(child_b)
            # Both children have two parents
            both_parents = (parent_ids[i], parent_ids[i + 1])
            offspring_parents.append(both_parents)
            offspring_parents.append(both_parents)
            i += 2
        else:
            offspring.append(selected[i])
            offspring_parents.append((parent_ids[i],))
            i += 1

    # Trim to exact size needed
    offspring = offspring[:remaining]
    offspring_parents = offspring_parents[:remaining]

    # 4. Mutation on all offspring (not elites) + assign lineage
    for j in range(len(offspring)):
        offspring[j] = mutate_parameters(offspring[j], config.mutation, rng)
        offspring[j] = mutate_structure(offspring[j], config.mutation, config.max_tree_depth, rng)
        if config.composition.enabled:
            offspring[j] = mutate_composition(offspring[j], rng, config.mutation.parameter_rate)
        # Assign new lineage identity
        offspring[j].lineage_id = next_lineage_id()
        offspring[j].parent_ids = offspring_parents[j]

    next_gen.extend(offspring)
    return next_gen
