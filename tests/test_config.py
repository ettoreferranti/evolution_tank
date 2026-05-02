"""Tests for configuration system."""

import pytest
from evolution_tank.config import Config, ConfigValidationError


class TestConfigDefaults:
    def test_load_without_file_uses_defaults(self):
        config = Config.load()
        assert config.arena.width == 800
        assert config.arena.height == 800
        assert config.match.team_size == 5
        assert config.evolution.population_size == 100

    def test_seed_is_generated_when_none(self):
        c1 = Config.load()
        c2 = Config.load()
        # Seeds should be different (extremely unlikely to collide)
        assert isinstance(c1.seed, int)
        assert isinstance(c2.seed, int)

    def test_all_tank_types_present(self):
        config = Config.load()
        assert "light" in config.tank_types
        assert "medium" in config.tank_types
        assert "heavy" in config.tank_types

    def test_tank_type_values(self):
        config = Config.load()
        light = config.tank_types["light"]
        heavy = config.tank_types["heavy"]
        assert light.hp < heavy.hp
        assert light.speed > heavy.speed
        assert light.damage < heavy.damage

    def test_terrain_types_present(self):
        config = Config.load()
        assert "open" in config.arena.terrain_types
        assert "wall" in config.arena.terrain_types
        assert "mud" in config.arena.terrain_types
        assert "road" in config.arena.terrain_types

    def test_wall_is_impassable(self):
        config = Config.load()
        wall = config.arena.terrain_types["wall"]
        assert not wall.passable
        assert wall.blocks_los

    def test_fog_of_war_defaults(self):
        config = Config.load()
        assert config.fog_of_war.enabled is True
        assert config.fog_of_war.share_team_vision is True

    def test_friendly_fire_default(self):
        config = Config.load()
        assert config.combat.friendly_fire is True


class TestConfigFromYAML:
    def test_load_from_settings_file(self):
        config = Config.load("config/settings.yaml")
        assert config.arena.width == 800
        assert config.match.best_of == 3

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            Config.load("nonexistent.yaml")

    def test_partial_override(self, tmp_path):
        override = tmp_path / "override.yaml"
        override.write_text("arena:\n  width: 1000\n")
        config = Config.load(str(override))
        assert config.arena.width == 1000
        assert config.arena.height == 800  # default preserved


class TestConfigValidation:
    def test_arena_width_too_small(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("arena:\n  width: 100\n")
        with pytest.raises(ConfigValidationError):
            Config.load(str(f))

    def test_arena_width_too_large(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("arena:\n  width: 5000\n")
        with pytest.raises(ConfigValidationError):
            Config.load(str(f))

    def test_negative_hp_rejected(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("tank_types:\n  light:\n    hp: -10\n")
        with pytest.raises(ConfigValidationError):
            Config.load(str(f))

    def test_zero_team_size_rejected(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("match:\n  team_size: 0\n")
        with pytest.raises(ConfigValidationError):
            Config.load(str(f))

    def test_team_size_over_10_rejected(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("match:\n  team_size: 15\n")
        with pytest.raises(ConfigValidationError):
            Config.load(str(f))


class TestConfigImmutability:
    def test_config_is_frozen(self):
        config = Config.load()
        with pytest.raises(AttributeError):
            config.seed = 999

    def test_arena_config_is_frozen(self):
        config = Config.load()
        with pytest.raises(AttributeError):
            config.arena.width = 1234


class TestConfigWithHelpers:
    def test_with_seed(self):
        config = Config.load()
        new_config = config.with_seed(42)
        assert new_config.seed == 42
        assert new_config.arena.width == config.arena.width

    def test_with_visualization(self):
        config = Config.load()
        new_config = config.with_visualization(enabled=False)
        assert new_config.visualization.enabled is False
        assert new_config.arena.width == config.arena.width
