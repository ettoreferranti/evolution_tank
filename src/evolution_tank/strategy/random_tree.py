"""Random tree generation — creates initial population for generation 0."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from evolution_tank.strategy.actions import (
    AimAt,
    Fire,
    MoveAway,
    MoveToSignal,
    MoveToward,
    Patrol,
    Repair,
    SeekCover,
    SignalAction,
)
from evolution_tank.strategy.behavior_tree import BehaviorTree
from evolution_tank.strategy.composites import SelectorNode, SequenceNode
from evolution_tank.strategy.conditions import (
    AllyNearby,
    AmmoBelow,
    EnemyVisible,
    HealthBelow,
    InRange,
    NearCover,
    TurretAimedAtMe,
    UnderFire,
)
from evolution_tank.strategy.nodes import BTNode, TargetSelector

if TYPE_CHECKING:
    from evolution_tank.config import EvolutionConfig

# Signal types that can be used
_SIGNAL_TYPES = ["ENEMY_SPOTTED", "HELP", "REGROUP", "ATTACK_HERE"]

# Target selectors for movement/aiming
_MOVE_TARGETS = [TargetSelector.NEAREST_ENEMY, TargetSelector.NEAREST_ALLY,
                 TargetSelector.LAST_KNOWN_ENEMY, TargetSelector.SIGNAL_POSITION]
_AIM_TARGETS = [TargetSelector.NEAREST_ENEMY, TargetSelector.LAST_KNOWN_ENEMY]


def _random_condition(rng: random.Random) -> BTNode:
    """Generate a random condition node with random parameters."""
    choice = rng.randint(0, 7)
    if choice == 0:
        return EnemyVisible()
    elif choice == 1:
        return HealthBelow(threshold=rng.uniform(0.1, 0.8))
    elif choice == 2:
        return AmmoBelow(count=rng.uniform(2.0, 15.0))
    elif choice == 3:
        return AllyNearby(distance=rng.uniform(50.0, 200.0))
    elif choice == 4:
        return UnderFire()
    elif choice == 5:
        return TurretAimedAtMe(tolerance=rng.uniform(5.0, 45.0))
    elif choice == 6:
        return InRange(distance=rng.uniform(50.0, 400.0))
    else:
        return NearCover(distance=rng.uniform(30.0, 150.0))


def _random_action(rng: random.Random) -> BTNode:
    """Generate a random action node with random parameters."""
    choice = rng.randint(0, 8)
    if choice == 0:
        return MoveToward(target=rng.choice(_MOVE_TARGETS),
                          speed=rng.uniform(0.3, 1.0))
    elif choice == 1:
        return MoveAway(target=rng.choice(_MOVE_TARGETS),
                        speed=rng.uniform(0.5, 1.0))
    elif choice == 2:
        return Patrol(speed=rng.uniform(0.3, 0.8))
    elif choice == 3:
        return SeekCover()
    elif choice == 4:
        return AimAt(target=rng.choice(_AIM_TARGETS))
    elif choice == 5:
        return Fire()
    elif choice == 6:
        return Repair()
    elif choice == 7:
        return SignalAction(signal_type=rng.choice(_SIGNAL_TYPES))
    else:
        return MoveToSignal(speed=rng.uniform(0.4, 1.0))


def _random_move_action(rng: random.Random) -> BTNode:
    """Generate a guaranteed-to-succeed movement action.

    Only Patrol is used here because it always succeeds regardless
    of game state (no enemies needed, no signals needed). Other movement
    actions like MoveToward or MoveToSignal can return FAILURE when
    their target doesn't exist, which would leave the tank idle.
    """
    return Patrol(speed=rng.uniform(0.5, 1.0))


def _random_subtree(rng: random.Random, depth: int, max_depth: int) -> BTNode:
    """Recursively generate a random subtree.

    At leaf depth, always returns a leaf (condition or action).
    At intermediate depth, may return a composite or leaf.
    """
    # At max depth or probabilistically, return a leaf
    if depth >= max_depth or (depth > 1 and rng.random() < 0.4):
        if rng.random() < 0.5:
            return _random_condition(rng)
        return _random_action(rng)

    # Generate a composite node
    is_sequence = rng.random() < 0.5
    num_children = rng.randint(2, 4)
    children: list[BTNode] = []

    if is_sequence:
        # Sequences typically start with conditions, then actions
        # Add 0-2 conditions, then 1-2 actions/subtrees
        num_conditions = rng.randint(0, min(2, num_children - 1))
        for _ in range(num_conditions):
            children.append(_random_condition(rng))
        for _ in range(num_children - num_conditions):
            children.append(_random_subtree(rng, depth + 1, max_depth))
        return SequenceNode(children=children)
    else:
        # Selectors have diverse children
        for _ in range(num_children):
            children.append(_random_subtree(rng, depth + 1, max_depth))
        return SelectorNode(children=children)


def _combat_branch(rng: random.Random) -> BTNode:
    """Generate a guaranteed combat branch: EnemyVisible → AimAt → Fire.

    Parameters are randomized but the structure ensures the tank will
    actually shoot at enemies it can see.
    """
    children: list[BTNode] = [EnemyVisible()]

    # Optionally add a range check
    if rng.random() < 0.5:
        children.append(InRange(distance=rng.uniform(100.0, 400.0)))

    children.append(AimAt(target=rng.choice(_AIM_TARGETS)))
    children.append(Fire())

    # Sometimes add a movement action (close in or retreat after firing)
    if rng.random() < 0.3:
        children.append(MoveToward(target=TargetSelector.NEAREST_ENEMY,
                                   speed=rng.uniform(0.3, 0.8)))

    return SequenceNode(children=children)


def _survival_branch(rng: random.Random) -> BTNode:
    """Generate a survival branch: HealthBelow → Repair or SeekCover."""
    threshold = rng.uniform(0.2, 0.5)
    if rng.random() < 0.5:
        return SequenceNode(children=[HealthBelow(threshold=threshold), Repair()])
    return SequenceNode(children=[HealthBelow(threshold=threshold), SeekCover()])


def generate_random_tree(rng: random.Random, max_depth: int = 6,
                         team_size: int | None = None,
                         composition_enabled: bool = False) -> BehaviorTree:
    """Generate a random behavior tree for the initial population.

    The root is always a Selector with guaranteed branches:
    - A survival branch (health check + repair/flee)
    - A combat branch (enemy visible + aim + fire)
    - 0-2 random branches for diversity
    - A fallback branch (patrol or move)

    Args:
        rng: Seeded random number generator.
        max_depth: Maximum tree depth (from config.evolution.max_tree_depth).
        team_size: If set, generate a random composition vector.
        composition_enabled: Whether to include composition in the genome.
    """
    branches: list[BTNode] = []

    # 1. Survival branch (guarded by HealthBelow — fails at full HP)
    branches.append(_survival_branch(rng))

    # 2. Combat branch (guarded by EnemyVisible — fails when no enemies seen)
    branches.append(_combat_branch(rng))

    # 3. Fallback is always a movement action so tanks don't just sit idle.
    #    This MUST be last — any random branch above could return SUCCESS
    #    and prevent the tank from ever moving.
    branches.append(_random_move_action(rng))

    root = SelectorNode(children=branches)

    composition = None
    if composition_enabled and team_size is not None and team_size > 0:
        composition = _random_composition(rng, team_size)

    return BehaviorTree(root=root, composition=composition)


def _random_composition(rng: random.Random, team_size: int) -> dict[str, int]:
    """Generate a random composition that sums to team_size."""
    types = ["light", "medium", "heavy"]
    counts = [0, 0, 0]
    for _ in range(team_size):
        counts[rng.randint(0, 2)] += 1
    return {t: c for t, c in zip(types, counts)}
