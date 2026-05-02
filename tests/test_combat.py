"""Tests for combat system."""

import pytest

from evolution_tank.config import Config
from evolution_tank.simulation.arena import Arena, Vector2, load_preset
from evolution_tank.simulation.combat import update_projectiles, PROJECTILE_RADIUS, TANK_HIT_RADIUS
from evolution_tank.tanks.tank import Tank, TankType, Projectile


@pytest.fixture
def config():
    return Config.load()


@pytest.fixture
def open_arena():
    return load_preset("open")


def _make_tank(id: int, team_id: int, pos: Vector2, config: Config, tank_type: str = "medium") -> Tank:
    return Tank(
        id=id, team_id=team_id, tank_type=TankType(tank_type),
        type_config=config.tank_types[tank_type], position=pos,
    )


class TestProjectile:
    def test_projectile_moves(self):
        p = Projectile(
            position=Vector2(100, 100),
            velocity=Vector2(10, 0),
            damage=25, owner_id=0, team_id=0, max_range=300,
        )
        p.update(1.0)
        assert p.position.x == pytest.approx(110)
        assert p.active

    def test_projectile_despawns_at_max_range(self):
        p = Projectile(
            position=Vector2(0, 0),
            velocity=Vector2(100, 0),
            damage=25, owner_id=0, team_id=0, max_range=50,
        )
        p.update(1.0)  # Travels 100, max range 50
        assert not p.active

    def test_shell_speed_differs_by_type(self, config):
        light = config.tank_types["light"]
        heavy = config.tank_types["heavy"]
        assert light.projectile_speed != heavy.projectile_speed


class TestHitDetection:
    def test_projectile_hits_enemy(self, config, open_arena):
        target = _make_tank(1, 1, Vector2(110, 100), config)
        shooter = _make_tank(0, 0, Vector2(100, 100), config)
        proj = Projectile(
            position=Vector2(105, 100), velocity=Vector2(10, 0),
            damage=25, owner_id=0, team_id=0, max_range=300,
        )
        initial_hp = target.hp
        remaining = update_projectiles([proj], open_arena, [shooter, target], 1.0, True)
        assert target.hp < initial_hp
        assert len(remaining) == 0

    def test_cannot_hit_self(self, config, open_arena):
        tank = _make_tank(0, 0, Vector2(100, 100), config)
        proj = Projectile(
            position=Vector2(100, 100), velocity=Vector2(0, 0),
            damage=25, owner_id=0, team_id=0, max_range=300,
        )
        initial_hp = tank.hp
        update_projectiles([proj], open_arena, [tank], 1.0, True)
        assert tank.hp == initial_hp

    def test_friendly_fire_on(self, config, open_arena):
        ally = _make_tank(1, 0, Vector2(110, 100), config)  # Same team
        shooter = _make_tank(0, 0, Vector2(100, 100), config)
        proj = Projectile(
            position=Vector2(105, 100), velocity=Vector2(10, 0),
            damage=25, owner_id=0, team_id=0, max_range=300,
        )
        initial_hp = ally.hp
        update_projectiles([proj], open_arena, [shooter, ally], 1.0, friendly_fire=True)
        assert ally.hp < initial_hp

    def test_friendly_fire_off(self, config, open_arena):
        ally = _make_tank(1, 0, Vector2(110, 100), config)
        shooter = _make_tank(0, 0, Vector2(100, 100), config)
        proj = Projectile(
            position=Vector2(105, 100), velocity=Vector2(10, 0),
            damage=25, owner_id=0, team_id=0, max_range=300,
        )
        initial_hp = ally.hp
        remaining = update_projectiles([proj], open_arena, [shooter, ally], 1.0, friendly_fire=False)
        assert ally.hp == initial_hp
        assert len(remaining) == 1  # Projectile passes through

    def test_wall_blocks_projectile(self, config):
        # Use default arena which has walls
        arena = load_preset("default")
        target = _make_tank(1, 1, Vector2(300, 300), config)
        proj = Projectile(
            position=Vector2(5, 5), velocity=Vector2(100, 100),
            damage=25, owner_id=0, team_id=0, max_range=1000,
        )
        remaining = update_projectiles([proj], arena, [target], 1.0, True)
        # Projectile should be blocked by boundary wall
        assert len(remaining) == 0

    def test_shooter_gets_hit_credit(self, config, open_arena):
        shooter = _make_tank(0, 0, Vector2(100, 100), config)
        target = _make_tank(1, 1, Vector2(110, 100), config)
        proj = Projectile(
            position=Vector2(105, 100), velocity=Vector2(10, 0),
            damage=25, owner_id=0, team_id=0, max_range=300,
        )
        update_projectiles([proj], open_arena, [shooter, target], 1.0, True)
        assert shooter.shots_hit == 1
        assert shooter.damage_dealt > 0

    def test_shooter_gets_kill_credit(self, config, open_arena):
        shooter = _make_tank(0, 0, Vector2(100, 100), config)
        target = _make_tank(1, 1, Vector2(110, 100), config)
        target.hp = 1  # Near death
        proj = Projectile(
            position=Vector2(105, 100), velocity=Vector2(10, 0),
            damage=1000, owner_id=0, team_id=0, max_range=300,
        )
        update_projectiles([proj], open_arena, [shooter, target], 1.0, True)
        assert shooter.kills == 1

    def test_multiple_projectiles(self, config, open_arena):
        shooter = _make_tank(0, 0, Vector2(50, 50), config)
        projs = [
            Projectile(Vector2(100 + i * 50, 100), Vector2(10, 0), 25, 0, 0, max_range=300)
            for i in range(5)
        ]
        remaining = update_projectiles(projs, open_arena, [shooter], 1.0, True)
        assert len(remaining) == 5  # All still active (no targets hit)


class TestDamageFormula:
    def test_effective_damage(self, config):
        tank = _make_tank(0, 0, Vector2(0, 0), config, "heavy")
        armor = config.tank_types["heavy"].armor  # 30
        raw = 50
        effective = tank.take_damage(raw)
        assert effective == raw - armor

    def test_damage_floored_at_zero(self, config):
        tank = _make_tank(0, 0, Vector2(0, 0), config, "heavy")
        effective = tank.take_damage(5)  # Less than 30 armor
        assert effective == 0
