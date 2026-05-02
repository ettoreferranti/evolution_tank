"""Mutation and crossover operators for behavior trees."""

from __future__ import annotations

import copy
import random
from typing import TYPE_CHECKING, Any

from evolution_tank.strategy.behavior_tree import BehaviorTree
from evolution_tank.strategy.nodes import BTNode
from evolution_tank.strategy.serialization import (
    ACTION_TYPES,
    COMPOSITE_TYPES,
    CONDITION_TYPES,
    deserialize_tree,
    serialize_tree,
)

if TYPE_CHECKING:
    from evolution_tank.config import MutationConfig


# ---------------------------------------------------------------------------
# Tree traversal helpers
# ---------------------------------------------------------------------------

def collect_nodes(node: BTNode) -> list[BTNode]:
    """Flatten a tree into a list of all nodes (pre-order)."""
    result = [node]
    for child in node.get_children():
        result.extend(collect_nodes(child))
    return result


def tree_depth(node: BTNode) -> int:
    """Compute the depth of a tree rooted at node."""
    children = node.get_children()
    if not children:
        return 1
    return 1 + max(tree_depth(c) for c in children)


# ---------------------------------------------------------------------------
# Parameter mutation
# ---------------------------------------------------------------------------

def mutate_parameters(tree: BehaviorTree, mutation_config: MutationConfig,
                      rng: random.Random) -> BehaviorTree:
    """Apply Gaussian parameter mutation to a behavior tree.

    Walks all nodes. For each numeric parameter, with probability
    `parameter_rate`, adds Gaussian noise with sigma `parameter_sigma`.
    String parameters (target selectors, signal types) are not mutated here.

    Returns a new tree (deep copy). The original is not modified.
    """
    # Deep copy via serialization round-trip
    data = serialize_tree(tree)
    new_tree = deserialize_tree(data)

    nodes = collect_nodes(new_tree.root)
    for node in nodes:
        params = node.get_params()
        if not params:
            continue

        mutated = {}
        for key, value in params.items():
            if isinstance(value, (int, float)):
                if rng.random() < mutation_config.parameter_rate:
                    # Apply Gaussian noise relative to the parameter value
                    noise = rng.gauss(0, mutation_config.parameter_sigma * max(abs(value), 1.0))
                    mutated[key] = value + noise
            # String params (target, signal_type) are left unchanged
            # They could be mutated categorically in structural mutation

        if mutated:
            node.set_params(mutated)

    return new_tree


# ---------------------------------------------------------------------------
# Composition mutation
# ---------------------------------------------------------------------------

def mutate_composition(tree: BehaviorTree, rng: random.Random,
                       mutation_rate: float = 0.1) -> BehaviorTree:
    """Mutate a tree's composition vector.

    With probability mutation_rate, swaps one unit from one tank type
    to another (e.g. trade a light for a heavy). The total always
    sums to the same team size.

    Returns a new tree. The original is not modified.
    """
    data = serialize_tree(tree)
    new_tree = deserialize_tree(data)

    if new_tree.composition is None:
        return new_tree

    if rng.random() >= mutation_rate:
        return new_tree

    comp = dict(new_tree.composition)
    types = [t for t, count in comp.items() if count > 0]
    all_types = list(comp.keys())

    if len(types) < 1 or len(all_types) < 2:
        return new_tree

    # Pick a type to remove one from
    donor = rng.choice(types)
    # Pick a different type to add one to
    receiver = rng.choice([t for t in all_types if t != donor])

    comp[donor] -= 1
    comp[receiver] = comp.get(receiver, 0) + 1
    new_tree.composition = comp
    return new_tree


# ---------------------------------------------------------------------------
# Structural mutation
# ---------------------------------------------------------------------------

def mutate_structure(tree: BehaviorTree, mutation_config: MutationConfig,
                     max_depth: int, rng: random.Random) -> BehaviorTree:
    """Apply structural mutation to a behavior tree.

    With probability `structural_rate`, picks one structural operation
    (weighted by insert/delete/swap/replace weights) and applies it.

    Returns a new tree. The original is not modified.
    """
    if rng.random() >= mutation_config.structural_rate:
        # No structural mutation this round
        return deserialize_tree(serialize_tree(tree))

    data = copy.deepcopy(serialize_tree(tree))

    # Pick operation by weight
    ops = [
        ("insert", mutation_config.insert_weight),
        ("delete", mutation_config.delete_weight),
        ("swap", mutation_config.swap_weight),
        ("replace", mutation_config.replace_weight),
    ]
    total = sum(w for _, w in ops)
    if total <= 0:
        return deserialize_tree(data)

    roll = rng.random() * total
    cumulative = 0.0
    chosen_op = ops[0][0]
    for op_name, weight in ops:
        cumulative += weight
        if roll < cumulative:
            chosen_op = op_name
            break

    if chosen_op == "insert":
        data = _structural_insert(data, max_depth, rng)
    elif chosen_op == "delete":
        data = _structural_delete(data, rng)
    elif chosen_op == "swap":
        data = _structural_swap(data, rng)
    elif chosen_op == "replace":
        data = _structural_replace(data, rng)

    return deserialize_tree(data)


def _random_leaf(rng: random.Random) -> dict[str, Any]:
    """Generate a random leaf node (condition or action) as a dict."""
    # Import here to avoid circular dependency at module level
    from evolution_tank.strategy.random_tree import _random_action, _random_condition
    if rng.random() < 0.5:
        node = _random_condition(rng)
    else:
        node = _random_action(rng)
    return node.to_dict()


def _structural_insert(data: dict, max_depth: int, rng: random.Random) -> dict:
    """Insert a new random node into the tree.

    Picks a random composite node and adds a new child to it.
    If the tree is already at max depth, inserts a leaf.
    """
    positions = _find_composite_positions(data)
    if not positions:
        return data

    pos = rng.choice(positions)
    parent = _get_subtree(data, pos) if pos else data

    current_depth = tree_depth(deserialize_tree(data).root)
    if current_depth >= max_depth:
        # Only insert a leaf to avoid exceeding depth
        new_node = _random_leaf(rng)
    else:
        # Could insert a leaf or a small subtree
        new_node = _random_leaf(rng)

    insert_idx = rng.randint(0, len(parent["children"]))
    parent["children"].insert(insert_idx, new_node)
    return data


def _structural_delete(data: dict, rng: random.Random) -> dict:
    """Delete a random node from the tree.

    For leaf children of composites: simply remove them.
    For composite children: promote one of their children to replace them.
    Never deletes the root. Ensures composites keep at least 2 children.
    """
    positions = _find_subtree_positions(data)
    if not positions:
        return data

    # Filter to positions where deletion is safe
    safe = []
    for pos in positions:
        # Find the parent composite
        parent = data
        for idx in pos[:-1]:
            parent = parent["children"][idx]
        if len(parent.get("children", [])) > 2:
            safe.append(pos)

    if not safe:
        return data

    pos = rng.choice(safe)
    parent = data
    for idx in pos[:-1]:
        parent = parent["children"][idx]

    target = parent["children"][pos[-1]]
    if "children" in target and target["children"]:
        # Promote a random child
        promoted = rng.choice(target["children"])
        parent["children"][pos[-1]] = promoted
    else:
        # Just remove the leaf
        parent["children"].pop(pos[-1])

    return data


def _structural_swap(data: dict, rng: random.Random) -> dict:
    """Swap two random subtrees within the same tree."""
    positions = _find_subtree_positions(data)
    if len(positions) < 2:
        return data

    pos_a, pos_b = rng.sample(positions, 2)

    # Check neither is ancestor of the other
    if _is_ancestor(pos_a, pos_b) or _is_ancestor(pos_b, pos_a):
        return data

    subtree_a = copy.deepcopy(_get_subtree(data, pos_a))
    subtree_b = copy.deepcopy(_get_subtree(data, pos_b))
    _set_subtree(data, pos_a, subtree_b)
    _set_subtree(data, pos_b, subtree_a)
    return data


def _structural_replace(data: dict, rng: random.Random) -> dict:
    """Replace a random leaf node with a different random leaf."""
    positions = _find_subtree_positions(data)
    if not positions:
        return data

    # Find leaf positions
    leaves = [p for p in positions if "children" not in _get_subtree(data, p)]
    if not leaves:
        return data

    pos = rng.choice(leaves)
    new_leaf = _random_leaf(rng)
    _set_subtree(data, pos, new_leaf)
    return data


def _find_composite_positions(data: dict, path: tuple = ()) -> list[tuple]:
    """Find positions of all composite nodes (including root)."""
    positions = []
    if data.get("type") in COMPOSITE_TYPES:
        positions.append(path)
    for i, child in enumerate(data.get("children", [])):
        positions.extend(_find_composite_positions(child, path + (i,)))
    return positions


def _is_ancestor(a: tuple, b: tuple) -> bool:
    """Check if path a is an ancestor of path b."""
    return len(a) < len(b) and b[:len(a)] == a


# ---------------------------------------------------------------------------
# Crossover
# ---------------------------------------------------------------------------

def crossover(parent_a: BehaviorTree, parent_b: BehaviorTree,
              max_depth: int, rng: random.Random) -> tuple[BehaviorTree, BehaviorTree]:
    """Produce two offspring by swapping random subtrees.

    Picks a random node in each parent and swaps them. If the resulting
    tree exceeds max_depth, falls back to returning mutated copies of
    the parents instead.

    Returns two new trees. The originals are not modified.
    """
    # Deep copy both via serialization
    data_a = serialize_tree(parent_a)
    data_b = serialize_tree(parent_b)

    # Find all subtree positions in the serialized dicts
    positions_a = _find_subtree_positions(data_a)
    positions_b = _find_subtree_positions(data_b)

    if not positions_a or not positions_b:
        # Can't crossover single-node trees
        return deserialize_tree(data_a), deserialize_tree(data_b)

    # Pick random positions to swap
    pos_a = rng.choice(positions_a)
    pos_b = rng.choice(positions_b)

    # Extract subtrees
    subtree_a = _get_subtree(data_a, pos_a)
    subtree_b = _get_subtree(data_b, pos_b)

    # Swap
    child_a = copy.deepcopy(data_a)
    child_b = copy.deepcopy(data_b)
    _set_subtree(child_a, pos_a, copy.deepcopy(subtree_b))
    _set_subtree(child_b, pos_b, copy.deepcopy(subtree_a))

    # Check depth limits
    tree_a = deserialize_tree(child_a)
    tree_b = deserialize_tree(child_b)

    if tree_depth(tree_a.root) > max_depth:
        tree_a = deserialize_tree(data_a)
    if tree_depth(tree_b.root) > max_depth:
        tree_b = deserialize_tree(data_b)

    return tree_a, tree_b


def _find_subtree_positions(data: dict, path: tuple = ()) -> list[tuple]:
    """Find all positions where subtrees can be swapped.

    Returns a list of paths (tuples of child indices) to each node
    that is a child of a composite. Excludes the root itself.
    """
    positions = []
    children = data.get("children", [])
    for i, child in enumerate(children):
        child_path = path + (i,)
        positions.append(child_path)
        positions.extend(_find_subtree_positions(child, child_path))
    return positions


def _get_subtree(data: dict, path: tuple) -> dict:
    """Get the subtree at the given path."""
    node = data
    for idx in path:
        node = node["children"][idx]
    return node


def _set_subtree(data: dict, path: tuple, subtree: dict) -> None:
    """Replace the subtree at the given path."""
    node = data
    for idx in path[:-1]:
        node = node["children"][idx]
    node["children"][path[-1]] = subtree
