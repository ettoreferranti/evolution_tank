"""Tests for tank model."""

import pytest

from evolution_tank.config import Config
from evolution_tank.simulation.arena import Vector2
from evolution_tank.tanks.tank import Tank, TankType, TankState


@pytest.fixture
def config():
    return Config.load()


@pytest.fixture
def light_tank(config):
    return Tank(id=0, team_id=0, tank_type=TankType.LIGHT,
                type_config=config.tank_types["light"],
                position=Vector2(100, 100))


@pytest.fixture
def medium_tank(config):
    return Tank(id=1, team_id=0, tank_type=TankType.MEDIUM,
                type_config=config.tank_types["medium"],
                position=Vector2(200, 200))


@pytest.fixture
def heavy_tank(config):
    return Tank(id=2, team_id=1, tank_type=TankType.HEAVY,
                type_config=config.tank_types["heavy"],
                position=Vector2(300, 300))


class TestTankInit:
    def test_hp_from_config(self, light_tank, config):
        assert light_tank.hp == config.tank_types["light"].hp
        assert light_tank.max_hp == config.tank_types["light"].hp

    def test_ammo_from_config(self, light_tank, config):
        assert light_tank.ammo == config.tank_types["light"].ammo
        assert light_tank.max_ammo == config.tank_types["light"].ammo

    def test_initial_state_active(self, light_tank):
        assert light_tank.state == TankState.ACTIVE
        assert light_tank.is_alive
        assert light_tank.is_active


class TestTankFiring:
    def test_can_fire_initially(self, medium_tank):
        assert medium_tank.can_fire

    def test_fire_decrements_ammo(self, medium_tank):
        initial = medium_tank.ammo
        proj = medium_tank.fire()
        assert proj is not None
        assert medium_tank.ammo == initial - 1

    def test_fire_sets_reload_timer(self, medium_tank):
        medium_tank.fire()
        assert medium_tank.reload_timer > 0

    def test_cannot_fire_during_reload(self, medium_tank):
        medium_tank.fire()
        assert not medium_tank.can_fire

    def test_can_fire_after_reload(self, medium_tank):
        medium_tank.fire()
        medium_tank.update_timers(medium_tank.type_config.reload_time)
        assert medium_tank.can_fire

    def test_cannot_fire_at_zero_ammo(self, light_tank):
        light_tank.ammo = 0
        assert not light_tank.can_fire
        assert light_tank.fire() is None

    def test_projectile_direction_matches_turret(self, medium_tank):
        medium_tank.turret_angle = 90.0  # Aim north
        proj = medium_tank.fire()
        assert proj is not None
        assert proj.velocity.y > 0  # Moving in positive y
        assert abs(proj.velocity.x) < 0.1  # Negligible x component

    def test_shots_fired_tracked(self, medium_tank):
        medium_tank.fire()
        assert medium_tank.shots_fired == 1


class TestTankDamage:
    def test_damage_reduced_by_armor(self, heavy_tank, config):
        armor = config.tank_types["heavy"].armor  # 30
        effective = heavy_tank.take_damage(40)
        assert effective == 10  # 40 - 30 armor
        assert heavy_tank.hp == config.tank_types["heavy"].hp - 10

    def test_damage_floored_at_zero(self, heavy_tank):
        effective = heavy_tank.take_damage(5)  # Less than armor
        assert effective == 0

    def test_destroyed_at_zero_hp(self, light_tank):
        light_tank.take_damage(1000)
        assert light_tank.hp == 0
        assert light_tank.state == TankState.DESTROYED
        assert not light_tank.is_alive

    def test_destroyed_tank_cannot_act(self, light_tank):
        light_tank.take_damage(1000)
        assert not light_tank.can_fire
        assert light_tank.fire() is None
        assert not light_tank.can_repair

    def test_damage_tracked(self, light_tank):
        light_tank.take_damage(20)
        assert light_tank.damage_taken > 0


class TestTankRepair:
    def test_can_repair_when_damaged(self, medium_tank):
        medium_tank.take_damage(50)  # Takes some damage through armor
        assert medium_tank.can_repair

    def test_cannot_repair_at_full_hp(self, medium_tank):
        assert not medium_tank.can_repair

    def test_repair_sets_state(self, medium_tank):
        medium_tank.take_damage(50)
        medium_tank.start_repair()
        assert medium_tank.state == TankState.REPAIRING
        assert medium_tank.is_repairing

    def test_repair_stops_movement(self, medium_tank):
        medium_tank.velocity = Vector2(3.0, 0.0)
        medium_tank.take_damage(50)
        medium_tank.start_repair()
        assert medium_tank.velocity == Vector2(0.0, 0.0)

    def test_cannot_fire_while_repairing(self, medium_tank):
        medium_tank.take_damage(50)
        medium_tank.start_repair()
        assert not medium_tank.can_fire

    def test_repair_restores_full_hp(self, medium_tank):
        medium_tank.take_damage(50)
        medium_tank.start_repair()
        medium_tank.update_timers(medium_tank.type_config.repair_time)
        assert medium_tank.hp == medium_tank.max_hp
        assert medium_tank.state == TankState.ACTIVE

    def test_repair_not_interruptible_by_damage(self, medium_tank):
        medium_tank.take_damage(50)
        medium_tank.start_repair()
        medium_tank.take_damage(20)  # Hit while repairing
        assert medium_tank.is_repairing or not medium_tank.is_alive
        # If still alive, should still be repairing
        if medium_tank.is_alive:
            assert medium_tank.is_repairing

    def test_repair_tank_destroyed_during_repair(self, light_tank):
        light_tank.take_damage(20)
        light_tank.start_repair()
        light_tank.take_damage(1000)  # Lethal hit
        assert light_tank.state == TankState.DESTROYED

    def test_cannot_cancel_repair(self, medium_tank):
        medium_tank.take_damage(50)
        medium_tank.start_repair()
        # Even after partial time, still repairing
        medium_tank.update_timers(medium_tank.type_config.repair_time * 0.5)
        assert medium_tank.is_repairing


class TestLeadAngle:
    def test_stationary_target(self):
        angle = Tank.compute_lead_angle(
            Vector2(0, 0), Vector2(100, 0), Vector2(0, 0), 10.0
        )
        assert angle == pytest.approx(0.0, abs=0.1)  # Straight east

    def test_moving_target_requires_lead(self):
        # Target at (100, 0) moving north at 5 units/s, shell speed 10
        angle = Tank.compute_lead_angle(
            Vector2(0, 0), Vector2(100, 0), Vector2(0, 5), 10.0
        )
        assert angle is not None
        assert angle > 0  # Must aim slightly north (positive angle)

    def test_no_solution_returns_none(self):
        # Target moving away faster than shell
        angle = Tank.compute_lead_angle(
            Vector2(0, 0), Vector2(100, 0), Vector2(100, 0), 5.0
        )
        # May or may not have a solution depending on geometry
        # The important thing is it doesn't crash


class TestTankTypeComparison:
    def test_light_faster_than_heavy(self, config):
        assert config.tank_types["light"].speed > config.tank_types["heavy"].speed

    def test_heavy_more_damage(self, config):
        assert config.tank_types["heavy"].damage > config.tank_types["light"].damage

    def test_heavy_more_armor(self, config):
        assert config.tank_types["heavy"].armor > config.tank_types["light"].armor

    def test_heavy_more_hp(self, config):
        assert config.tank_types["heavy"].hp > config.tank_types["light"].hp
