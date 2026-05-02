"""Evolution subsystem — fitness, mutation, selection, engine."""

from evolution_tank.evolution.engine import EvolutionEngine, GenerationResult
from evolution_tank.evolution.fitness import compute_average_fitness, compute_fitness
from evolution_tank.evolution.mutation import crossover, mutate_parameters, mutate_structure
from evolution_tank.evolution.selection import select_next_generation, tournament_select

__all__ = [
    "EvolutionEngine",
    "GenerationResult",
    "compute_average_fitness",
    "compute_fitness",
    "crossover",
    "mutate_parameters",
    "mutate_structure",
    "select_next_generation",
    "tournament_select",
]
