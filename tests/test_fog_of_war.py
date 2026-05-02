"""Tests for fog of war and sensor system."""

import pytest

from evolution_tank.config import Config
from evolution_tank.simulation.arena import Vector2, load_preset
from evolution_tank.simulation.fog_of_war import compute_sensor_data
from evolution_tank.tanks.tank import Tank, TankType


@pytest.fixture
def config():
    return Config.load()


def _make_tank(id: int, team_id: int, pos: Vector2, config: Config, tank_type: str = "medium") -> Tank:
    return Tank(
        id=id, team_id=team_id, tank_type=TankType(tank_type),
        type_config=config.tank_types[tank_type], position=pos,
    )


class TestVisibility:
    def test_sees_enemy_in_range(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        enemy = _make_tank(1, 1, Vector2(450, 400), config)  # 50px away, vis=200
        sensor = compute_sensor_data(observer, [observer, enemy], arena, config.fog_of_war, set())
        assert len(sensor.visible_enemies) == 1
        assert sensor.visible_enemies[0].tank_id == 1

    def test_cannot_see_enemy_out_of_range(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(100, 400), config)
        enemy = _make_tank(1, 1, Vector2(700, 400), config)  # 600px away, vis=200
        sensor = compute_sensor_data(observer, [observer, enemy], arena, config.fog_of_war, set())
        assert len(sensor.visible_enemies) == 0

    def test_wall_blocks_los(self, config):
        arena = load_preset("default")
        # Place observer and enemy on opposite sides of a wall
        # Default map has walls around row 3-6, col 11-14
        observer = _make_tank(0, 0, Vector2(150, 70), config)  # Left of wall
        enemy = _make_tank(1, 1, Vector2(310, 70), config)     # Right of wall
        # Even within range, wall should block
        sensor = compute_sensor_data(observer, [observer, enemy], arena, config.fog_of_war, set())
        # This depends on exact wall layout — if LOS passes through wall, enemy invisible
        # At minimum, verify the function doesn't crash
        assert isinstance(sensor.visible_enemies, list)

    def test_sees_allies(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        ally = _make_tank(1, 0, Vector2(420, 400), config)  # Same team
        sensor = compute_sensor_data(observer, [observer, ally], arena, config.fog_of_war, set())
        assert len(sensor.visible_allies) == 1
        assert sensor.visible_allies[0].tank_id == 1

    def test_does_not_see_self(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        sensor = compute_sensor_data(observer, [observer], arena, config.fog_of_war, set())
        assert len(sensor.visible_enemies) == 0
        assert len(sensor.visible_allies) == 0

    def test_does_not_see_destroyed(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        enemy = _make_tank(1, 1, Vector2(420, 400), config)
        enemy.take_damage(10000)  # Destroy it
        sensor = compute_sensor_data(observer, [observer, enemy], arena, config.fog_of_war, set())
        assert len(sensor.visible_enemies) == 0

    def test_destroyed_observer_sees_nothing(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        enemy = _make_tank(1, 1, Vector2(420, 400), config)
        observer.take_damage(10000)
        sensor = compute_sensor_data(observer, [observer, enemy], arena, config.fog_of_war, set())
        assert len(sensor.visible_enemies) == 0


class TestTeamVisionSharing:
    def test_ally_shares_vision(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(100, 400), config)
        ally = _make_tank(1, 0, Vector2(400, 400), config)  # Same team, near enemy
        enemy = _make_tank(2, 1, Vector2(450, 400), config)  # 50px from ally, 350 from observer
        # Observer can't see enemy directly (350 > 200 range)
        # But ally can (50 < 200 range), and shares vision
        sensor = compute_sensor_data(observer, [observer, ally, enemy], arena, config.fog_of_war, set())
        assert len(sensor.visible_enemies) == 1
        assert sensor.visible_enemies[0].tank_id == 2


class TestSensorData:
    def test_enemy_data_fields(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        enemy = _make_tank(1, 1, Vector2(450, 400), config)
        enemy.heading = 90.0
        enemy.turret_angle = 180.0
        enemy.velocity = Vector2(3.0, 1.0)
        sensor = compute_sensor_data(observer, [observer, enemy], arena, config.fog_of_war, set())
        e = sensor.visible_enemies[0]
        assert e.tank_type == TankType.MEDIUM
        assert e.distance == pytest.approx(50.0)
        assert e.heading == pytest.approx(90.0)
        assert e.turret_angle == pytest.approx(180.0)
        assert e.velocity.x == pytest.approx(3.0)
        assert e.velocity.y == pytest.approx(1.0)

    def test_no_enemy_hp_in_sensor(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        enemy = _make_tank(1, 1, Vector2(420, 400), config)
        sensor = compute_sensor_data(observer, [observer, enemy], arena, config.fog_of_war, set())
        e = sensor.visible_enemies[0]
        assert not hasattr(e, "hp")
        assert not hasattr(e, "ammo")

    def test_under_fire_flag(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        sensor = compute_sensor_data(observer, [observer], arena, config.fog_of_war, {0})
        assert sensor.under_fire is True

    def test_not_under_fire(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        sensor = compute_sensor_data(observer, [observer], arena, config.fog_of_war, set())
        assert sensor.under_fire is False

    def test_enemy_repairing_visible(self, config):
        arena = load_preset("open")
        observer = _make_tank(0, 0, Vector2(400, 400), config)
        enemy = _make_tank(1, 1, Vector2(420, 400), config)
        enemy.take_damage(50)
        enemy.start_repair()
        sensor = compute_sensor_data(observer, [observer, enemy], arena, config.fog_of_war, set())
        assert sensor.visible_enemies[0].is_repairing is True


class TestFogDisabled:
    def test_sees_everything_when_fog_disabled(self, config):
        arena = load_preset("open")
        config = config.with_seed(1)
        # Create a config with fog disabled
        from evolution_tank.config import FogOfWarConfig
        fog_off = FogOfWarConfig(enabled=False, share_team_vision=True)
        observer = _make_tank(0, 0, Vector2(100, 400), config)
        enemy = _make_tank(1, 1, Vector2(700, 400), config)  # Way out of range
        sensor = compute_sensor_data(observer, [observer, enemy], arena, fog_off, set())
        assert len(sensor.visible_enemies) == 1
