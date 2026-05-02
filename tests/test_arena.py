"""Tests for arena and map system."""

import random

import pytest

from evolution_tank.simulation.arena import Arena, Terrain, Vector2, load_preset, PRESETS


class TestVector2:
    def test_addition(self):
        assert Vector2(1, 2) + Vector2(3, 4) == Vector2(4, 6)

    def test_subtraction(self):
        assert Vector2(5, 3) - Vector2(1, 1) == Vector2(4, 2)

    def test_scalar_multiply(self):
        assert Vector2(2, 3) * 2 == Vector2(4, 6)
        assert 2 * Vector2(2, 3) == Vector2(4, 6)

    def test_length(self):
        assert Vector2(3, 4).length() == pytest.approx(5.0)

    def test_normalized(self):
        n = Vector2(3, 4).normalized()
        assert n.length() == pytest.approx(1.0)

    def test_zero_normalized(self):
        n = Vector2(0, 0).normalized()
        assert n.x == 0.0 and n.y == 0.0

    def test_distance(self):
        assert Vector2(0, 0).distance_to(Vector2(3, 4)) == pytest.approx(5.0)

    def test_angle_east(self):
        assert Vector2(1, 0).angle() == pytest.approx(0.0)

    def test_angle_north(self):
        assert Vector2(0, 1).angle() == pytest.approx(90.0)

    def test_from_angle_roundtrip(self):
        for deg in [0, 45, 90, 180, 270]:
            v = Vector2.from_angle(deg)
            assert v.angle() == pytest.approx(deg, abs=0.01)

    def test_dot_product(self):
        assert Vector2(1, 0).dot(Vector2(0, 1)) == pytest.approx(0.0)
        assert Vector2(1, 0).dot(Vector2(1, 0)) == pytest.approx(1.0)


class TestArena:
    def test_create_arena(self):
        a = Arena(400, 400, cell_size=20)
        assert a.width == 400
        assert a.height == 400
        assert a.cols == 20
        assert a.rows == 20

    def test_boundary_walls(self):
        a = Arena(400, 400, cell_size=20)
        # Top-left corner
        assert a.get_terrain_at_cell(0, 0) == Terrain.WALL
        # Top-right
        assert a.get_terrain_at_cell(0, 19) == Terrain.WALL
        # Bottom-left
        assert a.get_terrain_at_cell(19, 0) == Terrain.WALL
        # Interior should be open
        assert a.get_terrain_at_cell(5, 5) == Terrain.OPEN

    def test_set_terrain(self):
        a = Arena(400, 400, cell_size=20)
        a.set_terrain(5, 5, Terrain.MUD)
        assert a.get_terrain_at_cell(5, 5) == Terrain.MUD

    def test_out_of_bounds_is_wall(self):
        a = Arena(400, 400, cell_size=20)
        assert a.get_terrain_at_cell(-1, 0) == Terrain.WALL
        assert a.get_terrain_at_cell(100, 100) == Terrain.WALL

    def test_passable(self):
        a = Arena(400, 400, cell_size=20)
        assert a.is_passable(Vector2(100, 100))  # Interior
        assert not a.is_passable(Vector2(5, 5))  # Boundary wall

    def test_text_roundtrip(self):
        a = Arena(400, 400, cell_size=20)
        a.set_terrain(5, 5, Terrain.MUD)
        a.set_terrain(6, 6, Terrain.ROAD)
        text = a.to_text()
        b = Arena.from_text(text, cell_size=20)
        assert b.get_terrain_at_cell(5, 5) == Terrain.MUD
        assert b.get_terrain_at_cell(6, 6) == Terrain.ROAD
        assert b.get_terrain_at_cell(1, 1) == Terrain.OPEN

    def test_from_text_invalid_char(self):
        with pytest.raises(ValueError, match="Unknown terrain char"):
            Arena.from_text("WW\nWX\n", cell_size=20)


class TestPresets:
    def test_all_presets_load(self):
        for name in PRESETS:
            arena = load_preset(name)
            assert arena.width > 0
            assert arena.height > 0

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown map preset"):
            load_preset("nonexistent")

    def test_preset_has_boundary_walls(self):
        for name in PRESETS:
            arena = load_preset(name)
            # Check all edges are walls
            for col in range(arena.cols):
                assert arena.get_terrain_at_cell(0, col) == Terrain.WALL
                assert arena.get_terrain_at_cell(arena.rows - 1, col) == Terrain.WALL
            for row in range(arena.rows):
                assert arena.get_terrain_at_cell(row, 0) == Terrain.WALL
                assert arena.get_terrain_at_cell(row, arena.cols - 1) == Terrain.WALL


class TestSpawnPositions:
    def _spawn_config(self):
        return type("S", (), {"side": "opposite", "min_separation": 30, "cluster_spread": 50})()

    def test_spawn_returns_correct_team_count(self):
        arena = load_preset("open")
        positions = arena.compute_spawn_positions(2, 5, self._spawn_config(), random.Random(42))
        assert len(positions) == 2
        assert len(positions[0]) == 5
        assert len(positions[1]) == 5

    def test_spawn_on_passable_terrain(self):
        arena = load_preset("default")
        positions = arena.compute_spawn_positions(2, 5, self._spawn_config(), random.Random(42))
        for team in positions:
            for pos in team:
                assert arena.is_passable(pos), f"Spawn at ({pos.x:.0f}, {pos.y:.0f}) is on impassable terrain"

    def test_spawn_separation(self):
        arena = load_preset("open")
        cfg = self._spawn_config()
        positions = arena.compute_spawn_positions(2, 5, cfg, random.Random(42))
        for team in positions:
            for i, p1 in enumerate(team):
                for j, p2 in enumerate(team):
                    if i < j:
                        assert p1.distance_to(p2) >= cfg.min_separation * 0.9  # small tolerance

    def test_opposite_sides_are_apart(self):
        arena = load_preset("open")
        positions = arena.compute_spawn_positions(2, 3, self._spawn_config(), random.Random(42))
        # Centers of each team should be far apart
        avg_0 = Vector2(
            sum(p.x for p in positions[0]) / 3,
            sum(p.y for p in positions[0]) / 3,
        )
        avg_1 = Vector2(
            sum(p.x for p in positions[1]) / 3,
            sum(p.y for p in positions[1]) / 3,
        )
        assert avg_0.distance_to(avg_1) > arena.width * 0.5

    def test_spawn_deterministic_with_seed(self):
        arena = load_preset("open")
        cfg = self._spawn_config()
        p1 = arena.compute_spawn_positions(2, 5, cfg, random.Random(42))
        p2 = arena.compute_spawn_positions(2, 5, cfg, random.Random(42))
        for team_a, team_b in zip(p1, p2):
            for a, b in zip(team_a, team_b):
                assert a.x == b.x and a.y == b.y
