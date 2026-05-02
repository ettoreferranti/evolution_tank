"""Arena and map system — terrain grid, presets, spawn positions."""

from __future__ import annotations

import math
import random as _random
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evolution_tank.config import ArenaConfig, SpawnConfig


class Terrain(Enum):
    OPEN = "open"
    WALL = "wall"
    MUD = "mud"
    ROAD = "road"


# Character mapping for text-based map files
_CHAR_TO_TERRAIN: dict[str, Terrain] = {
    ".": Terrain.OPEN,
    "W": Terrain.WALL,
    "M": Terrain.MUD,
    "R": Terrain.ROAD,
}

_TERRAIN_TO_CHAR: dict[Terrain, str] = {v: k for k, v in _CHAR_TO_TERRAIN.items()}


@dataclass(frozen=True)
class TerrainInfo:
    terrain: Terrain
    speed_modifier: float
    passable: bool
    blocks_los: bool


@dataclass(frozen=True)
class Vector2:
    x: float
    y: float

    def __add__(self, other: Vector2) -> Vector2:
        return Vector2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vector2) -> Vector2:
        return Vector2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vector2:
        return Vector2(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Vector2:
        return self.__mul__(scalar)

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y)

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y

    def normalized(self) -> Vector2:
        ln = self.length()
        if ln < 1e-10:
            return Vector2(0.0, 0.0)
        return Vector2(self.x / ln, self.y / ln)

    def dot(self, other: Vector2) -> float:
        return self.x * other.x + self.y * other.y

    def distance_to(self, other: Vector2) -> float:
        return (self - other).length()

    def angle(self) -> float:
        """Angle in degrees from positive x-axis, range [0, 360)."""
        return math.degrees(math.atan2(self.y, self.x)) % 360

    @staticmethod
    def from_angle(degrees: float) -> Vector2:
        rad = math.radians(degrees)
        return Vector2(math.cos(rad), math.sin(rad))


class Arena:
    """Rectangular arena with a terrain grid."""

    def __init__(self, width: int, height: int, cell_size: int = 20) -> None:
        self.width = width
        self.height = height
        self.cell_size = cell_size
        self.cols = width // cell_size
        self.rows = height // cell_size
        # Grid stored as row-major: grid[row][col]
        self._grid: list[list[Terrain]] = [
            [Terrain.OPEN] * self.cols for _ in range(self.rows)
        ]
        # Set boundary walls
        self._set_boundary_walls()

    def _set_boundary_walls(self) -> None:
        for col in range(self.cols):
            self._grid[0][col] = Terrain.WALL
            self._grid[self.rows - 1][col] = Terrain.WALL
        for row in range(self.rows):
            self._grid[row][0] = Terrain.WALL
            self._grid[row][self.cols - 1] = Terrain.WALL

    def get_terrain_at_cell(self, row: int, col: int) -> Terrain:
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self._grid[row][col]
        return Terrain.WALL  # Out of bounds = wall

    def get_terrain_at_pos(self, pos: Vector2) -> Terrain:
        col = int(pos.x // self.cell_size)
        row = int(pos.y // self.cell_size)
        return self.get_terrain_at_cell(row, col)

    def set_terrain(self, row: int, col: int, terrain: Terrain) -> None:
        if 0 <= row < self.rows and 0 <= col < self.cols:
            self._grid[row][col] = terrain

    def is_passable(self, pos: Vector2) -> bool:
        return self.get_terrain_at_pos(pos) != Terrain.WALL

    def get_speed_modifier(self, pos: Vector2, config: ArenaConfig) -> float:
        terrain = self.get_terrain_at_pos(pos)
        terrain_cfg = config.terrain_types.get(terrain.value)
        if terrain_cfg is None:
            return 1.0
        return terrain_cfg.speed_modifier

    def blocks_los(self, pos: Vector2) -> bool:
        return self.get_terrain_at_pos(pos) == Terrain.WALL

    def cell_center(self, row: int, col: int) -> Vector2:
        return Vector2(
            (col + 0.5) * self.cell_size,
            (row + 0.5) * self.cell_size,
        )

    def to_text(self) -> str:
        lines = []
        for row in range(self.rows):
            line = "".join(_TERRAIN_TO_CHAR[self._grid[row][col]] for col in range(self.cols))
            lines.append(line)
        return "\n".join(lines)

    @classmethod
    def from_text(cls, text: str, cell_size: int = 20) -> Arena:
        lines = [line for line in text.strip().split("\n") if line]
        rows = len(lines)
        cols = len(lines[0])
        arena = cls(cols * cell_size, rows * cell_size, cell_size)
        for r, line in enumerate(lines):
            if len(line) != cols:
                raise ValueError(f"Row {r} has {len(line)} cols, expected {cols}")
            for c, ch in enumerate(line):
                if ch not in _CHAR_TO_TERRAIN:
                    raise ValueError(f"Unknown terrain char '{ch}' at row={r} col={c}")
                arena._grid[r][c] = _CHAR_TO_TERRAIN[ch]
        return arena

    def compute_spawn_positions(
        self,
        team_count: int,
        team_size: int,
        spawn_config: SpawnConfig,
        rng: _random.Random,
    ) -> list[list[Vector2]]:
        """Compute spawn positions for each team.

        Returns list of teams, each a list of Vector2 positions.
        """
        if spawn_config.side == "opposite":
            return self._spawn_opposite(team_count, team_size, spawn_config, rng)
        return self._spawn_random(team_count, team_size, spawn_config, rng)

    def _spawn_opposite(
        self,
        team_count: int,
        team_size: int,
        spawn_config: SpawnConfig,
        rng: _random.Random,
    ) -> list[list[Vector2]]:
        """Spawn teams on opposite/distributed sides of the map."""
        margin = self.cell_size * 2  # Stay away from boundary walls
        spread = spawn_config.cluster_spread
        teams: list[list[Vector2]] = []

        for team_idx in range(team_count):
            angle = (2 * math.pi * team_idx) / team_count
            # Center point on the map perimeter (inset by margin)
            cx = self.width / 2 + (self.width / 2 - margin) * math.cos(angle)
            cy = self.height / 2 + (self.height / 2 - margin) * math.sin(angle)

            positions: list[Vector2] = []
            for _ in range(team_size):
                # Try to find valid position near center
                for _attempt in range(100):
                    px = cx + rng.uniform(-spread, spread)
                    py = cy + rng.uniform(-spread, spread)
                    pos = Vector2(
                        max(margin, min(self.width - margin, px)),
                        max(margin, min(self.height - margin, py)),
                    )
                    if not self.is_passable(pos):
                        continue
                    # Check min separation from existing spawns
                    too_close = False
                    for existing in positions:
                        if pos.distance_to(existing) < spawn_config.min_separation:
                            too_close = True
                            break
                    if not too_close:
                        positions.append(pos)
                        break
                else:
                    # Fallback: place at center (shouldn't happen with reasonable maps)
                    positions.append(Vector2(cx, cy))

            teams.append(positions)
        return teams

    def _spawn_random(
        self,
        team_count: int,
        team_size: int,
        spawn_config: SpawnConfig,
        rng: _random.Random,
    ) -> list[list[Vector2]]:
        """Random spawn positions on passable terrain."""
        margin = self.cell_size * 2
        all_positions: list[Vector2] = []
        teams: list[list[Vector2]] = []

        for _ in range(team_count):
            positions: list[Vector2] = []
            for _ in range(team_size):
                for _attempt in range(200):
                    pos = Vector2(
                        rng.uniform(margin, self.width - margin),
                        rng.uniform(margin, self.height - margin),
                    )
                    if not self.is_passable(pos):
                        continue
                    too_close = any(
                        pos.distance_to(e) < spawn_config.min_separation
                        for e in all_positions + positions
                    )
                    if not too_close:
                        positions.append(pos)
                        break
                else:
                    positions.append(Vector2(self.width / 2, self.height / 2))
            teams.append(positions)
            all_positions.extend(positions)
        return teams


# ---------------------------------------------------------------------------
# Preset maps
# ---------------------------------------------------------------------------

_PRESET_DEFAULT = """\
WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
W......................................W
W......................................W
W...........WWWW.......................W
W...........W..W.......................W
W...........W..W........MMM............W
W..........WWWWW........MMM............W
W......................................W
W......................................W
W..MMM.................................W
W..MMM..........WWWWWW.................W
W...............W....W.................W
W...............W....W.................W
W...............WWWWWW.................W
W......................................W
W......................................W
W..............RRRRRRRRRRRR............W
W..............RRRRRRRRRRRR............W
W......................................W
W......................................W
W...............WWWWWW.................W
W...............W....W.................W
W...............W....W.................W
W...............WWWWWW.................W
W......................................W
W......................................W
W..........WWWWW........MMM............W
W...........W..W........MMM............W
W...........W..W.......................W
W...........WWWW.......................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
"""

_PRESET_OPEN = """\
WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
W......................................W
WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
"""

_PRESET_MAZE = """\
WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W....WWWW...WWWW...WWWW...WWWW.........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W....WWWW...WWWW...WWWW...WWWW.........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W....WWWW...WWWW...WWWW...WWWW.........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W....WWWW...WWWW...WWWW...WWWW.........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......W......W......W......W..........W
W......................................W
W......................................W
W......................................W
WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
"""

_PRESET_CORRIDORS = """\
WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
W......................................W
W.WWWWWWWWWWWWWWWWW.WWWWWWWWWWWWWWWWWW.W
W......................................W
W......................................W
W......................................W
W.WWWWWWWWWWWWWWWWW.WWWWWWWWWWWWWWWWWW.W
W......................................W
W......................................W
WRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRW
W......................................W
W......................................W
W.WWWWWWWWWWWWWWWWW.WWWWWWWWWWWWWWWWWW.W
W......................................W
W......................................W
W......................................W
W.WWWWWWWWWWWWWWWWW.WWWWWWWWWWWWWWWWWW.W
W..........MMM..........MMM............W
W..........MMM..........MMM............W
W......................................W
W.WWWWWWWWWWWWWWWWW.WWWWWWWWWWWWWWWWWW.W
W......................................W
W......................................W
W......................................W
W.WWWWWWWWWWWWWWWWW.WWWWWWWWWWWWWWWWWW.W
W......................................W
W......................................W
WRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRW
W......................................W
W......................................W
W.WWWWWWWWWWWWWWWWW.WWWWWWWWWWWWWWWWWW.W
W......................................W
W......................................W
W......................................W
W.WWWWWWWWWWWWWWWWW.WWWWWWWWWWWWWWWWWW.W
W......................................W
W......................................W
W......................................W
W......................................W
WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
"""


PRESETS: dict[str, str] = {
    "default": _PRESET_DEFAULT,
    "open": _PRESET_OPEN,
    "maze": _PRESET_MAZE,
    "corridors": _PRESET_CORRIDORS,
}


def load_preset(name: str, cell_size: int = 20) -> Arena:
    """Load a preset map by name."""
    if name not in PRESETS:
        raise ValueError(f"Unknown map preset '{name}'. Available: {list(PRESETS.keys())}")
    return Arena.from_text(PRESETS[name], cell_size)
