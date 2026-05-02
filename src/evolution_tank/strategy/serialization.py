"""Serialization — convert behavior trees to/from JSON-compatible dicts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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

# ---------------------------------------------------------------------------
# Node registry — maps type strings to factory functions
# ---------------------------------------------------------------------------

NODE_REGISTRY: dict[str, type[BTNode]] = {
    # Composites
    "selector": SelectorNode,
    "sequence": SequenceNode,
    # Conditions
    "enemy_visible": EnemyVisible,
    "health_below": HealthBelow,
    "ammo_below": AmmoBelow,
    "ally_nearby": AllyNearby,
    "under_fire": UnderFire,
    "turret_aimed_at_me": TurretAimedAtMe,
    "in_range": InRange,
    "near_cover": NearCover,
    # Actions
    "move_toward": MoveToward,
    "move_away": MoveAway,
    "patrol": Patrol,
    "seek_cover": SeekCover,
    "aim_at": AimAt,
    "fire": Fire,
    "repair": Repair,
    "signal": SignalAction,
    "move_to_signal": MoveToSignal,
}

# Which nodes are composites (have children)
COMPOSITE_TYPES = {"selector", "sequence"}

# Which nodes are conditions (no params that are targets)
CONDITION_TYPES = {
    "enemy_visible", "health_below", "ammo_below", "ally_nearby",
    "under_fire", "turret_aimed_at_me", "in_range", "near_cover",
}

ACTION_TYPES = {
    "move_toward", "move_away", "patrol", "seek_cover",
    "aim_at", "fire", "repair", "signal", "move_to_signal",
}


# ---------------------------------------------------------------------------
# Deserialization
# ---------------------------------------------------------------------------

def deserialize_node(data: dict[str, Any]) -> BTNode:
    """Recursively build a BTNode from a serialized dict."""
    node_type = data.get("type")
    if node_type is None:
        raise ValueError("Node dict missing 'type' field")
    if node_type not in NODE_REGISTRY:
        raise ValueError(f"Unknown node type: {node_type!r}")

    params = data.get("params", {})

    if node_type in COMPOSITE_TYPES:
        children_data = data.get("children", [])
        if not children_data:
            raise ValueError(f"Composite node {node_type!r} must have children")
        children = [deserialize_node(c) for c in children_data]
        cls = NODE_REGISTRY[node_type]
        return cls(children=children)

    # Leaf node — construct with params
    cls = NODE_REGISTRY[node_type]
    # Convert target strings to TargetSelector enum
    if "target" in params:
        params = dict(params)  # Don't mutate original
        params["target"] = TargetSelector(params["target"])

    # Filter params to only those accepted by __init__
    import inspect
    sig = inspect.signature(cls.__init__)
    valid_params = {k: v for k, v in params.items()
                    if k in sig.parameters and k != "self"}
    return cls(**valid_params)


def deserialize_tree(data: dict[str, Any]) -> BehaviorTree:
    """Build a BehaviorTree from a serialized dict."""
    root = deserialize_node(data)
    composition = data.get("composition")
    lineage_id = data.get("lineage_id")
    parent_ids = tuple(data.get("parent_ids", ()))
    return BehaviorTree(
        root=root, composition=composition,
        lineage_id=lineage_id, parent_ids=parent_ids,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize_tree(tree: BehaviorTree) -> dict[str, Any]:
    """Serialize a BehaviorTree to a JSON-compatible dict."""
    return tree.to_dict()


# ---------------------------------------------------------------------------
# JSON file I/O
# ---------------------------------------------------------------------------

def save_tree_json(tree: BehaviorTree, path: str | Path) -> None:
    """Save a behavior tree to a JSON file."""
    data = serialize_tree(tree)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_tree_json(path: str | Path) -> BehaviorTree:
    """Load a behavior tree from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return deserialize_tree(data)
