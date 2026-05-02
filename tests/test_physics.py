"""Tests for physics and movement system."""

import pytest

from evolution_tank.config import Config
from evolution_tank.simulation.arena import Arena, Vector2, load_preset, Terrain
from evolution_tank.simulation.physics import update_tank_movement, update_turret
from evolution_tank.tanks.tank import Tank, TankType, TankState


@pytest.fixture
def config():
    return Config.load()


def _make_tank(id: int, pos: Vector2, config: Config, heading: float = 0.0) -> Tank:
    return Tank(
        id=id, team_id=0, tank_type=TankType.MEDIUM,
        type_config=config.tank_types["medium"],
        position=pos, heading=heading,
    )


class TestMovement:
    def test_position_updates(self, config):
        arena = load_preset("open")
        tank = _make_tank(0, Vector2(400, 400), config, heading=0.0)
        update_tank_movement(tank, 0.0, 1.0, arena, config.arena, 1.0, [tank])
        assert tank.position.x > 400  # Moved east

    def test_acceleration(self, config):
        arena = load_preset("open")
        tank = _make_tank(0, Vector2(400, 400), config, heading=0.0)
        # First tick — starts from rest
        update_tank_movement(tank, 0.0, 1.0, arena, config.arena, 1.0, [tank])
        speed_after_1 = tank.speed
        # Should have accelerated but not reached max
        assert speed_after_1 > 0
        assert speed_after_1 <= config.tank_types["medium"].speed

    def test_deceleration(self, config):
        arena = load_preset("open")
        tank = _make_tank(0, Vector2(400, 400), config, heading=0.0)
        tank.velocity = Vector2(config.tank_types["medium"].speed, 0)
        update_tank_movement(tank, 0.0, 0.0, arena, config.arena, 1.0, [tank])
        assert tank.speed < config.tank_types["medium"].speed

    def test_turn_rate_clamped(self, config):
        arena = load_preset("open")
        tank = _make_tank(0, Vector2(400, 400), config, heading=0.0)
        # Request 180 degree turn in small dt
        dt = 0.01
        update_tank_movement(tank, 180.0, 0.0, arena, config.arena, dt, [tank])
        # Turn should be clamped — account for angle wrapping (e.g. 358.8 means -1.2)
        max_turn = config.tank_types["medium"].turn_rate * dt
        actual_turn = min(tank.heading, 360 - tank.heading)
        assert actual_turn <= max_turn + 0.01

    def test_no_movement_when_repairing(self, config):
        arena = load_preset("open")
        tank = _make_tank(0, Vector2(400, 400), config)
        tank.take_damage(50)
        tank.start_repair()
        old_pos = tank.position
        update_tank_movement(tank, 0.0, 1.0, arena, config.arena, 1.0, [tank])
        assert tank.position == old_pos  # Didn't move


class TestWallCollision:
    def test_wall_stops_tank(self, config):
        arena = load_preset("open")
        # Try to move into boundary wall
        tank = _make_tank(0, Vector2(25, 400), config, heading=180.0)  # Facing west toward wall
        tank.velocity = Vector2(-5, 0)
        update_tank_movement(tank, 180.0, 1.0, arena, config.arena, 1.0, [tank])
        # Should not pass through wall
        assert tank.position.x > 5


class TestTankCollision:
    def test_tanks_dont_overlap(self, config):
        arena = load_preset("open")
        t1 = _make_tank(0, Vector2(400, 400), config)
        t2 = _make_tank(1, Vector2(405, 400), config)  # Very close
        t2.team_id = 1
        update_tank_movement(t1, 0.0, 1.0, arena, config.arena, 0.1, [t1, t2])
        dist = t1.position.distance_to(t2.position)
        # Should maintain minimum separation
        assert dist >= 10  # 2 * TANK_RADIUS (8) minus some tolerance

    def test_collision_no_damage(self, config):
        arena = load_preset("open")
        t1 = _make_tank(0, Vector2(400, 400), config)
        t2 = _make_tank(1, Vector2(405, 400), config)
        hp1 = t1.hp
        hp2 = t2.hp
        update_tank_movement(t1, 0.0, 1.0, arena, config.arena, 0.1, [t1, t2])
        assert t1.hp == hp1
        assert t2.hp == hp2


class TestTerrainSpeedModifier:
    def test_mud_slows_tank(self, config):
        arena = Arena(400, 400, cell_size=20)
        # Set interior to mud
        for r in range(5, 15):
            for c in range(5, 15):
                arena.set_terrain(r, c, Terrain.MUD)

        tank_open = _make_tank(0, Vector2(50, 50), config, heading=0.0)
        tank_mud = _make_tank(1, Vector2(150, 150), config, heading=0.0)

        # Give both same initial velocity
        dt = 1.0
        update_tank_movement(tank_open, 0.0, 1.0, arena, config.arena, dt, [tank_open])
        update_tank_movement(tank_mud, 0.0, 1.0, arena, config.arena, dt, [tank_mud])

        # Mud tank should move less (lower max speed)
        dist_open = (tank_open.position - Vector2(50, 50)).length()
        dist_mud = (tank_mud.position - Vector2(150, 150)).length()
        assert dist_mud < dist_open


class TestTurretRotation:
    def test_turret_rotates_toward_target(self, config):
        tank = _make_tank(0, Vector2(400, 400), config)
        tank.turret_angle = 0.0
        update_turret(tank, 90.0, 1.0)
        assert tank.turret_angle > 0

    def test_turret_rotation_clamped(self, config):
        tank = _make_tank(0, Vector2(400, 400), config)
        tank.turret_angle = 0.0
        dt = 0.01
        update_turret(tank, 180.0, dt)
        max_rot = config.tank_types["medium"].turret_rotation_speed * dt
        actual_rot = min(tank.turret_angle, 360 - tank.turret_angle)
        assert actual_rot <= max_rot + 0.01

    def test_turret_independent_of_hull(self, config):
        arena = load_preset("open")
        tank = _make_tank(0, Vector2(400, 400), config)
        tank.turret_angle = 90.0
        # Turn hull but not turret target
        update_tank_movement(tank, 45.0, 0.0, arena, config.arena, 1.0, [tank])
        # Turret should still be near 90 (didn't change)
        assert tank.turret_angle == pytest.approx(90.0)

    def test_turret_no_rotation_while_repairing(self, config):
        tank = _make_tank(0, Vector2(400, 400), config)
        tank.turret_angle = 0.0
        tank.take_damage(50)
        tank.start_repair()
        update_turret(tank, 90.0, 1.0)
        assert tank.turret_angle == 0.0  # Didn't rotate
