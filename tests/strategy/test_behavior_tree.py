"""Tests for the behavior tree system — nodes, composites, conditions, actions,
serialization, random generation, and integration with the match runner."""

from __future__ import annotations

import json
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from evolution_tank.config import Config
from evolution_tank.simulation.arena import Arena, Vector2, load_preset
from evolution_tank.simulation.fog_of_war import (
    AllySensorData,
    EnemySensorData,
    SensorSnapshot,
)
from evolution_tank.simulation.match import Signal, TankCommand, run_match
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
from evolution_tank.strategy.behavior_tree import BehaviorTree, reset_lineage_counter
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
from evolution_tank.strategy.nodes import (
    BTNode,
    NodeStatus,
    TargetSelector,
    TickContext,
    TreeMemory,
    resolve_target,
)
from evolution_tank.strategy.random_tree import generate_random_tree
from evolution_tank.strategy.serialization import (
    deserialize_tree,
    load_tree_json,
    save_tree_json,
    serialize_tree,
)
from evolution_tank.tanks.tank import Tank, TankType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> Config:
    return Config.load("config/settings.yaml").with_seed(42)


def _make_tank(team_id: int = 0, position: Vector2 | None = None,
               hp: int | None = None, ammo: int | None = None) -> Tank:
    config = _make_config()
    pos = position or Vector2(400.0, 400.0)
    t = Tank(
        id=0, team_id=team_id, tank_type=TankType.MEDIUM,
        type_config=config.tank_types["medium"],
        position=pos, heading=0.0, turret_angle=0.0,
    )
    if hp is not None:
        t.hp = hp
    if ammo is not None:
        t.ammo = ammo
    return t


def _make_enemy(position: Vector2, distance: float = 100.0,
                velocity: Vector2 | None = None) -> EnemySensorData:
    return EnemySensorData(
        tank_id=99, tank_type=TankType.MEDIUM,
        position=position, distance=distance,
        angle=0.0, heading=180.0, turret_angle=0.0,
        velocity=velocity or Vector2(0.0, 0.0),
        is_repairing=False,
    )


def _make_ally(position: Vector2, distance: float = 50.0) -> AllySensorData:
    return AllySensorData(
        tank_id=1, tank_type=TankType.MEDIUM,
        position=position, distance=distance,
        is_repairing=False,
    )


def _make_ctx(tank: Tank | None = None,
              enemies: list[EnemySensorData] | None = None,
              allies: list[AllySensorData] | None = None,
              under_fire: bool = False,
              signals: list | None = None) -> TickContext:
    arena = load_preset("open")
    t = tank or _make_tank()
    sensor = SensorSnapshot(
        visible_enemies=enemies or [],
        visible_allies=allies or [],
        under_fire=under_fire,
        signals=signals or [],
    )
    return TickContext(
        tank=t,
        sensor=sensor,
        command=TankCommand(),
        arena=arena,
        memory=TreeMemory(),
        tick=100,
    )


# ===========================================================================
# NodeStatus & TargetSelector
# ===========================================================================

class TestNodeStatus:
    def test_values(self):
        assert NodeStatus.SUCCESS.value == "success"
        assert NodeStatus.FAILURE.value == "failure"


class TestTargetSelector:
    def test_values(self):
        assert TargetSelector.NEAREST_ENEMY.value == "nearest_enemy"
        assert TargetSelector.SIGNAL_POSITION.value == "signal_position"


# ===========================================================================
# Composite nodes
# ===========================================================================

class _FixedNode(BTNode):
    """Test helper: returns a fixed status."""
    def __init__(self, status: NodeStatus):
        self._status = status
        self.called = False

    def tick(self, ctx: TickContext) -> NodeStatus:
        self.called = True
        return self._status

    def to_dict(self):
        return {"type": "fixed", "params": {"status": self._status.value}}


class TestSelectorNode:
    def test_returns_success_on_first_success(self):
        fail = _FixedNode(NodeStatus.FAILURE)
        success = _FixedNode(NodeStatus.SUCCESS)
        not_reached = _FixedNode(NodeStatus.SUCCESS)

        selector = SelectorNode([fail, success, not_reached])
        ctx = _make_ctx()
        assert selector.tick(ctx) == NodeStatus.SUCCESS
        assert fail.called
        assert success.called
        assert not not_reached.called

    def test_returns_failure_when_all_fail(self):
        nodes = [_FixedNode(NodeStatus.FAILURE) for _ in range(3)]
        selector = SelectorNode(nodes)
        ctx = _make_ctx()
        assert selector.tick(ctx) == NodeStatus.FAILURE
        assert all(n.called for n in nodes)

    def test_serialization(self):
        selector = SelectorNode([EnemyVisible(), Fire()])
        d = selector.to_dict()
        assert d["type"] == "selector"
        assert len(d["children"]) == 2


class TestSequenceNode:
    def test_returns_failure_on_first_failure(self):
        success = _FixedNode(NodeStatus.SUCCESS)
        fail = _FixedNode(NodeStatus.FAILURE)
        not_reached = _FixedNode(NodeStatus.SUCCESS)

        sequence = SequenceNode([success, fail, not_reached])
        ctx = _make_ctx()
        assert sequence.tick(ctx) == NodeStatus.FAILURE
        assert success.called
        assert fail.called
        assert not not_reached.called

    def test_returns_success_when_all_succeed(self):
        nodes = [_FixedNode(NodeStatus.SUCCESS) for _ in range(3)]
        sequence = SequenceNode(nodes)
        ctx = _make_ctx()
        assert sequence.tick(ctx) == NodeStatus.SUCCESS

    def test_get_children(self):
        children = [Fire(), Repair()]
        seq = SequenceNode(children)
        assert len(seq.get_children()) == 2


# ===========================================================================
# Condition nodes
# ===========================================================================

class TestEnemyVisible:
    def test_success_when_enemies_present(self):
        enemy = _make_enemy(Vector2(500.0, 400.0))
        ctx = _make_ctx(enemies=[enemy])
        assert EnemyVisible().tick(ctx) == NodeStatus.SUCCESS

    def test_failure_when_no_enemies(self):
        ctx = _make_ctx()
        assert EnemyVisible().tick(ctx) == NodeStatus.FAILURE


class TestHealthBelow:
    def test_success_when_low(self):
        tank = _make_tank(hp=20)  # 20/100 = 0.2
        ctx = _make_ctx(tank=tank)
        assert HealthBelow(threshold=0.3).tick(ctx) == NodeStatus.SUCCESS

    def test_failure_when_healthy(self):
        tank = _make_tank(hp=80)
        ctx = _make_ctx(tank=tank)
        assert HealthBelow(threshold=0.3).tick(ctx) == NodeStatus.FAILURE

    def test_params(self):
        node = HealthBelow(threshold=0.5)
        assert node.get_params() == {"threshold": 0.5}
        node.set_params({"threshold": 0.7})
        assert node.threshold == 0.7

    def test_clamped(self):
        node = HealthBelow(threshold=1.5)
        assert node.threshold == 1.0


class TestAmmoBelow:
    def test_success_when_low(self):
        tank = _make_tank(ammo=3)
        ctx = _make_ctx(tank=tank)
        assert AmmoBelow(count=5.0).tick(ctx) == NodeStatus.SUCCESS

    def test_failure_when_enough(self):
        tank = _make_tank(ammo=10)
        ctx = _make_ctx(tank=tank)
        assert AmmoBelow(count=5.0).tick(ctx) == NodeStatus.FAILURE


class TestAllyNearby:
    def test_success_when_ally_close(self):
        ally = _make_ally(Vector2(420.0, 400.0), distance=20.0)
        ctx = _make_ctx(allies=[ally])
        assert AllyNearby(distance=50.0).tick(ctx) == NodeStatus.SUCCESS

    def test_failure_when_no_allies(self):
        ctx = _make_ctx()
        assert AllyNearby(distance=50.0).tick(ctx) == NodeStatus.FAILURE


class TestUnderFire:
    def test_success_when_under_fire(self):
        ctx = _make_ctx(under_fire=True)
        assert UnderFire().tick(ctx) == NodeStatus.SUCCESS

    def test_failure_when_safe(self):
        ctx = _make_ctx(under_fire=False)
        assert UnderFire().tick(ctx) == NodeStatus.FAILURE


class TestTurretAimedAtMe:
    def test_success_when_aimed(self):
        # Enemy at (500, 400), turret angle pointing back at tank at (400, 400)
        # Angle from enemy to us is 180 degrees
        enemy = EnemySensorData(
            tank_id=99, tank_type=TankType.MEDIUM,
            position=Vector2(500.0, 400.0), distance=100.0,
            angle=0.0, heading=180.0, turret_angle=180.0,
            velocity=Vector2(0.0, 0.0), is_repairing=False,
        )
        ctx = _make_ctx(enemies=[enemy])
        assert TurretAimedAtMe(tolerance=15.0).tick(ctx) == NodeStatus.SUCCESS

    def test_failure_when_not_aimed(self):
        enemy = EnemySensorData(
            tank_id=99, tank_type=TankType.MEDIUM,
            position=Vector2(500.0, 400.0), distance=100.0,
            angle=0.0, heading=180.0, turret_angle=90.0,  # Pointing up, not at us
            velocity=Vector2(0.0, 0.0), is_repairing=False,
        )
        ctx = _make_ctx(enemies=[enemy])
        assert TurretAimedAtMe(tolerance=15.0).tick(ctx) == NodeStatus.FAILURE


class TestInRange:
    def test_success(self):
        enemy = _make_enemy(Vector2(500.0, 400.0), distance=80.0)
        ctx = _make_ctx(enemies=[enemy])
        assert InRange(distance=100.0).tick(ctx) == NodeStatus.SUCCESS

    def test_failure(self):
        enemy = _make_enemy(Vector2(500.0, 400.0), distance=200.0)
        ctx = _make_ctx(enemies=[enemy])
        assert InRange(distance=100.0).tick(ctx) == NodeStatus.FAILURE


class TestNearCover:
    def test_success_on_map_with_walls(self):
        arena = load_preset("default")
        # Place tank near a wall
        tank = _make_tank(position=Vector2(100.0, 100.0))
        sensor = SensorSnapshot([], [], False)
        ctx = TickContext(
            tank=tank, sensor=sensor, command=TankCommand(),
            arena=arena, memory=TreeMemory(), tick=0,
        )
        # Default map has boundary walls, so near_cover should succeed at edges
        result = NearCover(distance=150.0).tick(ctx)
        # This depends on map layout, but boundary walls should be within 150px
        assert result == NodeStatus.SUCCESS

    def test_failure_in_open_center(self):
        arena = load_preset("open")
        # Place tank in center of open map — far from walls
        tank = _make_tank(position=Vector2(400.0, 400.0))
        sensor = SensorSnapshot([], [], False)
        ctx = TickContext(
            tank=tank, sensor=sensor, command=TankCommand(),
            arena=arena, memory=TreeMemory(), tick=0,
        )
        result = NearCover(distance=30.0).tick(ctx)
        assert result == NodeStatus.FAILURE


# ===========================================================================
# Action nodes
# ===========================================================================

class TestMoveToward:
    def test_sets_heading_and_speed(self):
        enemy = _make_enemy(Vector2(600.0, 400.0), distance=200.0)
        ctx = _make_ctx(enemies=[enemy])
        result = MoveToward(target=TargetSelector.NEAREST_ENEMY, speed=0.9).tick(ctx)
        assert result == NodeStatus.SUCCESS
        assert ctx.command.desired_heading is not None
        assert ctx.command.desired_speed == 0.9

    def test_failure_when_no_target(self):
        ctx = _make_ctx()
        result = MoveToward(target=TargetSelector.NEAREST_ENEMY).tick(ctx)
        assert result == NodeStatus.FAILURE

    def test_params(self):
        node = MoveToward(target=TargetSelector.NEAREST_ALLY, speed=0.5)
        params = node.get_params()
        assert params["target"] == "nearest_ally"
        assert params["speed"] == 0.5


class TestMoveAway:
    def test_sets_heading_away(self):
        enemy = _make_enemy(Vector2(600.0, 400.0), distance=200.0)
        ctx = _make_ctx(enemies=[enemy])
        result = MoveAway(target=TargetSelector.NEAREST_ENEMY, speed=1.0).tick(ctx)
        assert result == NodeStatus.SUCCESS
        # Heading should be roughly 180 degrees (away from east)
        assert ctx.command.desired_heading is not None


class TestPatrol:
    def test_sets_heading_and_advances_waypoint(self):
        ctx = _make_ctx()
        patrol = Patrol(speed=0.6)
        result = patrol.tick(ctx)
        assert result == NodeStatus.SUCCESS
        assert ctx.command.desired_heading is not None
        assert ctx.command.desired_speed == 0.6

    def test_advances_waypoint_when_close(self):
        # Place tank near first waypoint (25% of 800 = 200, 200)
        tank = _make_tank(position=Vector2(200.0, 200.0))
        ctx = _make_ctx(tank=tank)
        patrol = Patrol(speed=0.6)
        patrol.tick(ctx)
        # Should have advanced to next waypoint
        assert ctx.memory.patrol_waypoint_index == 1


class TestAimAt:
    def test_sets_turret_angle(self):
        enemy = _make_enemy(Vector2(600.0, 400.0), distance=200.0)
        ctx = _make_ctx(enemies=[enemy])
        result = AimAt(target=TargetSelector.NEAREST_ENEMY).tick(ctx)
        assert result == NodeStatus.SUCCESS
        assert ctx.command.desired_turret_angle is not None

    def test_failure_when_no_target(self):
        ctx = _make_ctx()
        result = AimAt(target=TargetSelector.NEAREST_ENEMY).tick(ctx)
        assert result == NodeStatus.FAILURE


class TestFire:
    def test_sets_fire_true(self):
        ctx = _make_ctx()
        result = Fire().tick(ctx)
        assert result == NodeStatus.SUCCESS
        assert ctx.command.fire is True


class TestRepair:
    def test_sets_repair_true(self):
        ctx = _make_ctx()
        result = Repair().tick(ctx)
        assert result == NodeStatus.SUCCESS
        assert ctx.command.repair is True


class TestSignalAction:
    def test_sets_signal(self):
        ctx = _make_ctx()
        result = SignalAction(signal_type="HELP").tick(ctx)
        assert result == NodeStatus.SUCCESS
        assert ctx.command.signal_type == "HELP"
        assert ctx.command.signal_position is not None


class TestMoveToSignal:
    def test_moves_to_signal(self):
        signal = Signal(
            signal_type="ENEMY_SPOTTED",
            position=Vector2(600.0, 600.0),
            sender_id=1, team_id=0, tick=90,
        )
        ctx = _make_ctx(signals=[signal])
        result = MoveToSignal(speed=0.8).tick(ctx)
        assert result == NodeStatus.SUCCESS
        assert ctx.command.desired_heading is not None

    def test_failure_when_no_signals(self):
        ctx = _make_ctx()
        result = MoveToSignal().tick(ctx)
        assert result == NodeStatus.FAILURE


class TestSeekCover:
    def test_on_map_with_walls(self):
        arena = load_preset("default")
        tank = _make_tank(position=Vector2(100.0, 100.0))
        enemy = _make_enemy(Vector2(200.0, 100.0), distance=100.0)
        sensor = SensorSnapshot([enemy], [], False)
        ctx = TickContext(
            tank=tank, sensor=sensor, command=TankCommand(),
            arena=arena, memory=TreeMemory(), tick=0,
        )
        result = SeekCover().tick(ctx)
        # Should find cover near boundary walls
        assert result == NodeStatus.SUCCESS
        assert ctx.command.desired_heading is not None


# ===========================================================================
# Target resolution
# ===========================================================================

class TestResolveTarget:
    def test_nearest_enemy(self):
        near = _make_enemy(Vector2(450.0, 400.0), distance=50.0)
        far = _make_enemy(Vector2(600.0, 400.0), distance=200.0)
        # Override tank_id to avoid duplicate
        far = EnemySensorData(
            tank_id=98, tank_type=far.tank_type, position=far.position,
            distance=far.distance, angle=far.angle, heading=far.heading,
            turret_angle=far.turret_angle, velocity=far.velocity,
            is_repairing=far.is_repairing,
        )
        ctx = _make_ctx(enemies=[far, near])
        pos = resolve_target(TargetSelector.NEAREST_ENEMY, ctx)
        assert pos == near.position

    def test_nearest_ally(self):
        ally = _make_ally(Vector2(420.0, 400.0), distance=20.0)
        ctx = _make_ctx(allies=[ally])
        pos = resolve_target(TargetSelector.NEAREST_ALLY, ctx)
        assert pos == ally.position

    def test_last_known_enemy(self):
        ctx = _make_ctx()
        ctx.memory.last_known_enemy_pos = Vector2(300.0, 300.0)
        pos = resolve_target(TargetSelector.LAST_KNOWN_ENEMY, ctx)
        assert pos == Vector2(300.0, 300.0)

    def test_signal_position(self):
        signal = Signal("ENEMY_SPOTTED", Vector2(500.0, 500.0), 1, 0, 50)
        ctx = _make_ctx(signals=[signal])
        pos = resolve_target(TargetSelector.SIGNAL_POSITION, ctx)
        assert pos == Vector2(500.0, 500.0)

    def test_returns_none_when_empty(self):
        ctx = _make_ctx()
        assert resolve_target(TargetSelector.NEAREST_ENEMY, ctx) is None
        assert resolve_target(TargetSelector.NEAREST_ALLY, ctx) is None
        assert resolve_target(TargetSelector.LAST_KNOWN_ENEMY, ctx) is None
        assert resolve_target(TargetSelector.SIGNAL_POSITION, ctx) is None


# ===========================================================================
# BehaviorTree
# ===========================================================================

class TestBehaviorTree:
    def test_evaluate_returns_command(self):
        """The architecture doc's example tree should produce reasonable output."""
        tree = BehaviorTree(root=SelectorNode([
            SequenceNode([HealthBelow(0.3), Repair()]),
            SequenceNode([EnemyVisible(), AimAt(), Fire()]),
            Patrol(speed=0.6),
        ]))
        arena = load_preset("open")

        # No enemies, healthy — should patrol
        tank = _make_tank()
        sensor = SensorSnapshot([], [], False)
        cmd = tree.evaluate(tank, sensor, arena)
        assert cmd.desired_speed == 0.6
        assert cmd.fire is False
        assert cmd.repair is False

    def test_low_hp_triggers_repair(self):
        tree = BehaviorTree(root=SelectorNode([
            SequenceNode([HealthBelow(0.3), Repair()]),
            Patrol(speed=0.6),
        ]))
        arena = load_preset("open")
        tank = _make_tank(hp=10)  # 10/100 = 0.1 < 0.3
        sensor = SensorSnapshot([], [], False)
        cmd = tree.evaluate(tank, sensor, arena)
        assert cmd.repair is True

    def test_enemy_triggers_combat(self):
        tree = BehaviorTree(root=SelectorNode([
            SequenceNode([EnemyVisible(), AimAt(), Fire()]),
            Patrol(speed=0.6),
        ]))
        arena = load_preset("open")
        tank = _make_tank()
        enemy = _make_enemy(Vector2(600.0, 400.0), distance=200.0)
        sensor = SensorSnapshot([enemy], [], False)
        cmd = tree.evaluate(tank, sensor, arena)
        assert cmd.fire is True
        assert cmd.desired_turret_angle is not None

    def test_memory_updates(self):
        tree = BehaviorTree(root=Patrol())
        arena = load_preset("open")
        tank = _make_tank()
        enemy = _make_enemy(Vector2(600.0, 400.0))
        sensor = SensorSnapshot([enemy], [], False)
        tree.evaluate(tank, sensor, arena, tick=10)
        assert tree.memory.last_known_enemy_pos == Vector2(600.0, 400.0)
        assert tree.memory.last_known_enemy_tick == 10

    def test_reset(self):
        tree = BehaviorTree(root=Patrol())
        tree.memory.last_known_enemy_pos = Vector2(1.0, 1.0)
        tree.reset()
        assert tree.memory.last_known_enemy_pos is None

    def test_to_strategy_fn(self):
        tree = BehaviorTree(root=SelectorNode([
            SequenceNode([EnemyVisible(), Fire()]),
            Patrol(),
        ]))
        arena = load_preset("open")
        strategy_fn = tree.to_strategy_fn(arena)
        tank = _make_tank()
        sensor = SensorSnapshot([], [], False)
        cmd = strategy_fn(tank, sensor)
        assert isinstance(cmd, TankCommand)


# ===========================================================================
# Serialization
# ===========================================================================

class TestSerialization:
    def _example_tree_dict(self) -> dict:
        return {
            "type": "selector",
            "children": [
                {
                    "type": "sequence",
                    "children": [
                        {"type": "health_below", "params": {"threshold": 0.3}},
                        {"type": "repair"},
                    ],
                },
                {
                    "type": "sequence",
                    "children": [
                        {"type": "enemy_visible"},
                        {"type": "aim_at", "params": {"target": "nearest_enemy"}},
                        {"type": "fire"},
                    ],
                },
                {"type": "patrol", "params": {"speed": 0.6}},
            ],
        }

    def test_roundtrip(self):
        data = self._example_tree_dict()
        tree = deserialize_tree(data)
        result = serialize_tree(tree)
        # Strip lineage metadata (runtime-assigned, not in original data)
        result.pop("lineage_id", None)
        result.pop("parent_ids", None)
        assert result == data

    def test_deserialize_creates_correct_types(self):
        data = self._example_tree_dict()
        tree = deserialize_tree(data)
        root = tree.root
        assert isinstance(root, SelectorNode)
        children = root.get_children()
        assert len(children) == 3
        assert isinstance(children[0], SequenceNode)
        assert isinstance(children[2], Patrol)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown node type"):
            deserialize_tree({"type": "nonexistent"})

    def test_missing_type_raises(self):
        with pytest.raises(ValueError, match="missing 'type'"):
            deserialize_tree({})

    def test_composite_without_children_raises(self):
        with pytest.raises(ValueError, match="must have children"):
            deserialize_tree({"type": "selector", "children": []})

    def test_json_file_io(self, tmp_path):
        data = self._example_tree_dict()
        tree = deserialize_tree(data)
        path = tmp_path / "test_tree.json"
        save_tree_json(tree, path)
        loaded = load_tree_json(path)
        # Lineage IDs are preserved through JSON save/load
        assert serialize_tree(loaded)["type"] == data["type"]
        assert serialize_tree(loaded)["children"] == data["children"]

    def test_all_node_types_serialize(self):
        """Every node type should serialize and deserialize cleanly."""
        nodes = [
            {"type": "enemy_visible"},
            {"type": "health_below", "params": {"threshold": 0.5}},
            {"type": "ammo_below", "params": {"count": 5.0}},
            {"type": "ally_nearby", "params": {"distance": 100.0}},
            {"type": "under_fire"},
            {"type": "turret_aimed_at_me", "params": {"tolerance": 20.0}},
            {"type": "in_range", "params": {"distance": 150.0}},
            {"type": "near_cover", "params": {"distance": 60.0}},
            {"type": "move_toward", "params": {"target": "nearest_enemy", "speed": 0.8}},
            {"type": "move_away", "params": {"target": "nearest_enemy", "speed": 1.0}},
            {"type": "patrol", "params": {"speed": 0.6}},
            {"type": "seek_cover"},
            {"type": "aim_at", "params": {"target": "nearest_enemy"}},
            {"type": "fire"},
            {"type": "repair"},
            {"type": "signal", "params": {"signal_type": "HELP"}},
            {"type": "move_to_signal", "params": {"speed": 0.8}},
        ]
        for node_data in nodes:
            # Wrap each in a selector so it's a valid tree
            tree_data = {"type": "selector", "children": [node_data]}
            tree = deserialize_tree(tree_data)
            result = serialize_tree(tree)
            assert result["children"][0] == node_data, f"Failed for {node_data['type']}"


# ===========================================================================
# Random tree generation
# ===========================================================================

class TestRandomTree:
    def test_generates_valid_tree(self):
        rng = random.Random(42)
        tree = generate_random_tree(rng, max_depth=6)
        assert isinstance(tree, BehaviorTree)
        assert isinstance(tree.root, SelectorNode)

    def test_deterministic_with_same_seed(self):
        reset_lineage_counter(1)
        tree1 = generate_random_tree(random.Random(123), max_depth=6)
        reset_lineage_counter(1)
        tree2 = generate_random_tree(random.Random(123), max_depth=6)
        assert serialize_tree(tree1) == serialize_tree(tree2)

    def test_different_seeds_produce_different_trees(self):
        tree1 = generate_random_tree(random.Random(1), max_depth=6)
        tree2 = generate_random_tree(random.Random(2), max_depth=6)
        # Compare structure only, not lineage IDs
        d1 = serialize_tree(tree1)
        d2 = serialize_tree(tree2)
        d1.pop("lineage_id", None)
        d2.pop("lineage_id", None)
        assert d1 != d2

    def test_serialization_roundtrip(self):
        rng = random.Random(42)
        tree = generate_random_tree(rng, max_depth=6)
        data = serialize_tree(tree)
        restored = deserialize_tree(data)
        assert serialize_tree(restored) == data

    def test_generates_multiple_unique(self):
        """Generate several trees, ensure diversity."""
        trees = []
        for seed in range(20):
            tree = generate_random_tree(random.Random(seed), max_depth=6)
            trees.append(serialize_tree(tree))
        # At least half should be unique
        unique = len(set(json.dumps(t, sort_keys=True) for t in trees))
        assert unique >= 10


# ===========================================================================
# Integration — run a match with BT strategies
# ===========================================================================

class TestIntegration:
    def test_bt_strategies_in_match(self):
        """Behavior tree strategies should work in a real match."""
        config = _make_config()
        arena = load_preset("open")
        rng = random.Random(42)

        spawn = arena.compute_spawn_positions(2, 3, config.match.spawn, rng)
        center = Vector2(arena.width / 2, arena.height / 2)

        # Build two BT strategies
        aggressive_tree = BehaviorTree(root=SelectorNode([
            SequenceNode([EnemyVisible(), AimAt(), Fire()]),
            SequenceNode([
                EnemyVisible(),
                MoveToward(target=TargetSelector.NEAREST_ENEMY, speed=0.8),
            ]),
            Patrol(speed=0.7),
        ]))

        defensive_tree = BehaviorTree(root=SelectorNode([
            SequenceNode([HealthBelow(0.3), Repair()]),
            SequenceNode([
                EnemyVisible(),
                InRange(distance=200.0),
                AimAt(),
                Fire(),
            ]),
            SequenceNode([
                EnemyVisible(),
                MoveAway(target=TargetSelector.NEAREST_ENEMY, speed=0.9),
            ]),
            Patrol(speed=0.5),
        ]))

        tanks = []
        strategies = {}
        tank_id = 0
        for team_id in range(2):
            tree = aggressive_tree if team_id == 0 else defensive_tree
            strategy_fn = tree.to_strategy_fn(arena)
            for i in range(3):
                pos = spawn[team_id][i]
                heading = (center - pos).angle()
                t = Tank(
                    id=tank_id, team_id=team_id, tank_type=TankType.MEDIUM,
                    type_config=config.tank_types["medium"],
                    position=pos, heading=heading, turret_angle=heading,
                )
                tanks.append(t)
                strategies[tank_id] = strategy_fn
                tank_id += 1

        result = run_match(config, arena, tanks, strategies)
        assert result is not None
        assert result.total_ticks > 0
        assert len(result.team_results) == 2
