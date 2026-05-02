"""Pygame renderer — draws battles in real time."""

from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING

import pygame

from evolution_tank.simulation.arena import Arena, Terrain, Vector2
from evolution_tank.simulation.match import MatchState
from evolution_tank.tanks.tank import Tank, TankType, TankState

if TYPE_CHECKING:
    from evolution_tank.config import Config


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

TERRAIN_COLORS: dict[Terrain, tuple[int, int, int]] = {
    Terrain.OPEN: (34, 139, 34),      # forest green
    Terrain.WALL: (64, 64, 64),       # dark gray
    Terrain.MUD: (139, 119, 42),      # dark khaki
    Terrain.ROAD: (169, 169, 169),    # silver gray
}

TEAM_COLORS: list[tuple[int, int, int]] = [
    (65, 105, 225),    # royal blue
    (220, 20, 60),     # crimson
    (50, 205, 50),     # lime green
    (255, 165, 0),     # orange
]

COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_RED = (200, 30, 30)
COLOR_GREEN = (30, 200, 30)
COLOR_YELLOW = (255, 255, 0)
COLOR_DARK_BG = (20, 20, 20)
COLOR_HP_BG = (60, 60, 60)
COLOR_PROJECTILE = (255, 220, 50)
COLOR_REPAIR = (100, 200, 255)
COLOR_DESTROYED = (80, 80, 80)

# Tank drawing sizes (half-dimensions for the hull rectangle)
HULL_SIZES: dict[str, tuple[int, int]] = {
    # (half_length, half_width) — length along heading, width perpendicular
    "light":  (5, 3),
    "medium": (7, 4),
    "heavy":  (9, 6),
}
TURRET_LENGTH = 11
TURRET_WIDTH = 2
HP_BAR_WIDTH = 18
HP_BAR_HEIGHT = 3
HP_BAR_OFFSET_Y = -14
MUZZLE_FLASH_TICKS = 4  # How long a muzzle flash lasts

# UI panel
UI_PANEL_HEIGHT = 48


class BattleRenderer:
    """Renders a battle using Pygame."""

    def __init__(self, config: Config, arena: Arena) -> None:
        self.config = config
        self.arena = arena

        self.win_w = config.visualization.window_width
        self.win_h = config.visualization.window_height

        # Scale factors: map → screen
        self.arena_display_h = self.win_h - UI_PANEL_HEIGHT
        self.scale_x = self.win_w / arena.width
        self.scale_y = self.arena_display_h / arena.height

        self.speed_multiplier = config.visualization.default_speed
        self.paused = False
        self.show_fog = False
        self.fog_team: int | None = None  # Which team's perspective

        # Pre-render terrain surface
        self._terrain_surface: pygame.Surface | None = None

        # Track muzzle flashes: tank_id → ticks remaining
        self._muzzle_flash: dict[int, int] = {}
        # Track previous ammo to detect firing
        self._prev_ammo: dict[int, int] = {}

        self._init_pygame()

    def _init_pygame(self) -> None:
        pygame.init()
        pygame.display.set_caption("Evolution Tank")
        self.screen = pygame.display.set_mode((self.win_w, self.win_h))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("monospace", 14)
        self.font_large = pygame.font.SysFont("monospace", 18, bold=True)
        self._terrain_surface = self._render_terrain()

    def _render_terrain(self) -> pygame.Surface:
        """Pre-render the terrain to a surface (called once)."""
        surf = pygame.Surface((self.win_w, self.arena_display_h))
        cell_w = self.arena.cell_size * self.scale_x
        cell_h = self.arena.cell_size * self.scale_y
        for row in range(self.arena.rows):
            for col in range(self.arena.cols):
                terrain = self.arena.get_terrain_at_cell(row, col)
                color = TERRAIN_COLORS.get(terrain, TERRAIN_COLORS[Terrain.OPEN])
                rect = pygame.Rect(
                    int(col * cell_w), int(row * cell_h),
                    int(cell_w) + 1, int(cell_h) + 1,
                )
                pygame.draw.rect(surf, color, rect)
        return surf

    def _map_to_screen(self, pos: Vector2) -> tuple[int, int]:
        return (int(pos.x * self.scale_x), int(pos.y * self.scale_y))

    # ------------------------------------------------------------------
    # Main render
    # ------------------------------------------------------------------

    def render_tick(self, state: MatchState, arena: Arena) -> bool:
        """Render one frame. Returns False if window was closed."""
        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return False
            if event.type == pygame.KEYDOWN:
                self._handle_key(event)

        if self.paused:
            # Still render but skip sim ticks
            self._draw_frame(state)
            self.clock.tick(30)
            return True

        self._draw_frame(state)
        # Cap FPS based on speed
        target_fps = self.config.match.ticks_per_second * self.speed_multiplier
        self.clock.tick(min(target_fps, 240))
        return True

    def _handle_key(self, event: pygame.event.Event) -> None:
        key = event.key
        char = getattr(event, "unicode", "")
        if key == pygame.K_SPACE:
            self.paused = not self.paused
        elif char == "-" or key == pygame.K_KP_MINUS:
            self.speed_multiplier = max(1, self.speed_multiplier - 1)
            self.paused = False
        elif char == "+" or key == pygame.K_KP_PLUS:
            self.speed_multiplier = min(10, self.speed_multiplier + 1)
            self.paused = False
        elif pygame.K_1 <= key <= pygame.K_9:
            self.speed_multiplier = key - pygame.K_0
            self.paused = False
        elif key == pygame.K_0:
            self.speed_multiplier = 10
            self.paused = False
        elif key == pygame.K_f:
            # Cycle fog: off → team 0 → team 1 → ... → off
            if not self.show_fog:
                self.show_fog = True
                self.fog_team = 0
            elif self.fog_team is not None:
                team_ids = sorted(set(t.team_id for t in self._last_tanks))
                idx = team_ids.index(self.fog_team) if self.fog_team in team_ids else -1
                if idx + 1 < len(team_ids):
                    self.fog_team = team_ids[idx + 1]
                else:
                    self.show_fog = False
                    self.fog_team = None
        elif key == pygame.K_ESCAPE or key == pygame.K_q:
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    def _draw_frame(self, state: MatchState) -> None:
        self._last_tanks = state.tanks

        # Detect muzzle flashes (who just fired?)
        for tank in state.tanks:
            prev = self._prev_ammo.get(tank.id)
            if prev is not None and tank.ammo < prev:
                self._muzzle_flash[tank.id] = MUZZLE_FLASH_TICKS
            self._prev_ammo[tank.id] = tank.ammo

        # Terrain
        self.screen.blit(self._terrain_surface, (0, 0))

        # Fog of war overlay
        if self.show_fog and self.fog_team is not None:
            self._draw_fog_overlay(state)

        # Projectiles — draw as small bright streaks
        for proj in state.projectiles:
            if proj.active:
                sx, sy = self._map_to_screen(proj.position)
                # Trail: draw a short line behind the projectile
                trail = proj.velocity.normalized() * -4
                tx, ty = int(sx + trail.x * self.scale_x), int(sy + trail.y * self.scale_y)
                pygame.draw.line(self.screen, COLOR_PROJECTILE, (tx, ty), (sx, sy), 2)
                pygame.draw.circle(self.screen, COLOR_WHITE, (sx, sy), 2)

        # Tanks
        for tank in state.tanks:
            self._draw_tank(tank)

        # Decay muzzle flashes
        expired = [tid for tid, t in self._muzzle_flash.items() if t <= 0]
        for tid in expired:
            del self._muzzle_flash[tid]
        for tid in self._muzzle_flash:
            self._muzzle_flash[tid] -= 1

        # UI panel
        self._draw_ui(state)

        pygame.display.flip()

    # ------------------------------------------------------------------
    # Tank drawing
    # ------------------------------------------------------------------

    def _rotate_point(self, cx: float, cy: float, px: float, py: float, angle_deg: float) -> tuple[int, int]:
        """Rotate point (px,py) around (cx,cy) by angle_deg."""
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        dx = px - cx
        dy = py - cy
        return (int(cx + dx * cos_a - dy * sin_a),
                int(cy + dx * sin_a + dy * cos_a))

    def _draw_tank(self, tank: Tank) -> None:
        sx, sy = self._map_to_screen(tank.position)
        team_color = TEAM_COLORS[tank.team_id % len(TEAM_COLORS)]
        # Darker shade for tracks
        track_color = tuple(max(0, c - 60) for c in team_color)

        if not tank.is_alive:
            # Destroyed — darkened hull with fire marks
            hl, hw = HULL_SIZES.get(tank.tank_type.value, HULL_SIZES["medium"])
            corners = [
                self._rotate_point(sx, sy, sx - hl, sy - hw, tank.heading),
                self._rotate_point(sx, sy, sx + hl, sy - hw, tank.heading),
                self._rotate_point(sx, sy, sx + hl, sy + hw, tank.heading),
                self._rotate_point(sx, sy, sx - hl, sy + hw, tank.heading),
            ]
            pygame.draw.polygon(self.screen, COLOR_DESTROYED, corners)
            pygame.draw.polygon(self.screen, (40, 40, 40), corners, 1)
            # Fire/smoke mark
            pygame.draw.circle(self.screen, (60, 20, 10), (sx, sy), 3)
            return

        hl, hw = HULL_SIZES.get(tank.tank_type.value, HULL_SIZES["medium"])

        # --- Tracks (two rectangles on either side of hull) ---
        track_inset = 1
        track_w = 2  # track thickness
        for side in [-1, 1]:
            track_corners = [
                self._rotate_point(sx, sy, sx - hl, sy + side * (hw + track_w), tank.heading),
                self._rotate_point(sx, sy, sx + hl, sy + side * (hw + track_w), tank.heading),
                self._rotate_point(sx, sy, sx + hl, sy + side * hw, tank.heading),
                self._rotate_point(sx, sy, sx - hl, sy + side * hw, tank.heading),
            ]
            pygame.draw.polygon(self.screen, track_color, track_corners)

        # --- Hull body (rotated rectangle) ---
        hull_corners = [
            self._rotate_point(sx, sy, sx - hl, sy - hw, tank.heading),
            self._rotate_point(sx, sy, sx + hl + 2, sy - hw + 1, tank.heading),  # front taper
            self._rotate_point(sx, sy, sx + hl + 2, sy + hw - 1, tank.heading),
            self._rotate_point(sx, sy, sx - hl, sy + hw, tank.heading),
        ]
        pygame.draw.polygon(self.screen, team_color, hull_corners)
        pygame.draw.polygon(self.screen, COLOR_BLACK, hull_corners, 1)

        # --- Turret base (small circle at center) ---
        turret_base_r = max(2, hw - 1)
        pygame.draw.circle(self.screen, team_color, (sx, sy), turret_base_r)
        pygame.draw.circle(self.screen, COLOR_BLACK, (sx, sy), turret_base_r, 1)

        # --- Gun barrel (line from center outward at turret_angle) ---
        barrel_len = TURRET_LENGTH + (2 if tank.tank_type == TankType.HEAVY else 0)
        barrel_end_x = sx + math.cos(math.radians(tank.turret_angle)) * barrel_len
        barrel_end_y = sy + math.sin(math.radians(tank.turret_angle)) * barrel_len
        # Barrel outline
        pygame.draw.line(self.screen, COLOR_BLACK,
                         (sx, sy), (int(barrel_end_x), int(barrel_end_y)), TURRET_WIDTH + 2)
        # Barrel fill
        pygame.draw.line(self.screen, team_color,
                         (sx, sy), (int(barrel_end_x), int(barrel_end_y)), TURRET_WIDTH)

        # --- Muzzle flash ---
        if tank.id in self._muzzle_flash:
            flash_r = 4 + (2 if tank.tank_type == TankType.HEAVY else 0)
            pygame.draw.circle(self.screen, COLOR_YELLOW,
                               (int(barrel_end_x), int(barrel_end_y)), flash_r)
            pygame.draw.circle(self.screen, COLOR_WHITE,
                               (int(barrel_end_x), int(barrel_end_y)), flash_r // 2)

        # --- Repair indicator ---
        if tank.is_repairing:
            outer_r = max(hl, hw) + 4
            pygame.draw.circle(self.screen, COLOR_REPAIR, (sx, sy), outer_r, 2)
            # Wrench icon: small + sign
            pygame.draw.line(self.screen, COLOR_REPAIR, (sx - 3, sy), (sx + 3, sy), 1)
            pygame.draw.line(self.screen, COLOR_REPAIR, (sx, sy - 3), (sx, sy + 3), 1)

        # --- Reload indicator (small arc below tank) ---
        if tank.reload_timer > 0:
            reload_frac = 1.0 - (tank.reload_timer / tank.type_config.reload_time)
            reload_bar_w = HP_BAR_WIDTH
            bar_x = sx - reload_bar_w // 2
            bar_y = sy + max(hl, hw) + 4
            pygame.draw.rect(self.screen, (40, 40, 40), (bar_x, bar_y, reload_bar_w, 2))
            fill_w = int(reload_bar_w * reload_frac)
            if fill_w > 0:
                pygame.draw.rect(self.screen, (200, 200, 50), (bar_x, bar_y, fill_w, 2))

        # --- HP bar ---
        hp_frac = tank.hp / tank.max_hp
        bar_x = sx - HP_BAR_WIDTH // 2
        bar_y = sy + HP_BAR_OFFSET_Y
        pygame.draw.rect(self.screen, COLOR_HP_BG,
                         (bar_x, bar_y, HP_BAR_WIDTH, HP_BAR_HEIGHT))
        fill_color = COLOR_GREEN if hp_frac > 0.5 else (COLOR_YELLOW if hp_frac > 0.25 else COLOR_RED)
        fill_w = int(HP_BAR_WIDTH * hp_frac)
        if fill_w > 0:
            pygame.draw.rect(self.screen, fill_color,
                             (bar_x, bar_y, fill_w, HP_BAR_HEIGHT))

    # ------------------------------------------------------------------
    # Fog of war
    # ------------------------------------------------------------------

    def _draw_fog_overlay(self, state: MatchState) -> None:
        fog_surface = pygame.Surface((self.win_w, self.arena_display_h), pygame.SRCALPHA)
        fog_surface.fill((0, 0, 0, 160))  # Dark overlay

        # Cut out visibility circles for the selected team
        for tank in state.tanks:
            if tank.team_id == self.fog_team and tank.is_alive:
                sx, sy = self._map_to_screen(tank.position)
                vis_r = int(tank.type_config.visibility_range * self.scale_x)
                pygame.draw.circle(fog_surface, (0, 0, 0, 0), (sx, sy), vis_r)

        self.screen.blit(fog_surface, (0, 0))

    # ------------------------------------------------------------------
    # UI panel
    # ------------------------------------------------------------------

    def _draw_ui(self, state: MatchState) -> None:
        panel_y = self.win_h - UI_PANEL_HEIGHT
        # Background
        pygame.draw.rect(self.screen, COLOR_DARK_BG,
                         (0, panel_y, self.win_w, UI_PANEL_HEIGHT))
        pygame.draw.line(self.screen, COLOR_WHITE, (0, panel_y), (self.win_w, panel_y))

        y = panel_y + 4

        # Tick counter
        max_ticks = self.config.match.max_ticks
        time_txt = f"Tick: {state.tick} / {max_ticks}" if max_ticks > 0 else f"Tick: {state.tick}"
        self._text(time_txt, 10, y, COLOR_WHITE)

        # Speed
        speed_txt = "PAUSED" if self.paused else f"Speed: {self.speed_multiplier}x"
        self._text(speed_txt, 200, y, COLOR_YELLOW if self.paused else COLOR_WHITE)

        # Fog
        if self.show_fog and self.fog_team is not None:
            fog_color = TEAM_COLORS[self.fog_team % len(TEAM_COLORS)]
            self._text(f"FOG: Team {self.fog_team}", 320, y, fog_color)
        else:
            self._text("FOG: off", 320, y, COLOR_WHITE)

        # Team stats
        team_data: dict[int, dict] = {}
        for tank in state.tanks:
            if tank.team_id not in team_data:
                team_data[tank.team_id] = {"alive": 0, "total": 0, "damage": 0.0}
            team_data[tank.team_id]["total"] += 1
            if tank.is_alive:
                team_data[tank.team_id]["alive"] += 1
            team_data[tank.team_id]["damage"] += tank.damage_dealt

        y2 = panel_y + 24
        x = 10
        for team_id in sorted(team_data.keys()):
            td = team_data[team_id]
            color = TEAM_COLORS[team_id % len(TEAM_COLORS)]
            txt = f"T{team_id}: {td['alive']}/{td['total']} alive, dmg:{td['damage']:.0f}"
            self._text(txt, x, y2, color)
            x += 260

        # Controls help (right side)
        help_txt = "[Space]Pause [0-9]Speed [+/-] [F]Fog [Q]Quit"
        self._text(help_txt, self.win_w - 380, y, (150, 150, 150))

    def _text(self, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
        surf = self.font.render(text, True, color)
        self.screen.blit(surf, (x, y))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def show_result(self, result) -> None:
        """Show match result overlay for a few seconds."""
        if result.winning_team_id is not None:
            color = TEAM_COLORS[result.winning_team_id % len(TEAM_COLORS)]
            txt = f"TEAM {result.winning_team_id} WINS!"
        else:
            color = COLOR_WHITE
            txt = "DRAW!"

        overlay = pygame.Surface((self.win_w, self.arena_display_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 100))
        self.screen.blit(overlay, (0, 0))

        result_surf = self.font_large.render(txt, True, color)
        rx = (self.win_w - result_surf.get_width()) // 2
        ry = (self.arena_display_h - result_surf.get_height()) // 2
        self.screen.blit(result_surf, (rx, ry))

        ticks_txt = f"{result.total_ticks} ticks"
        if result.timed_out:
            ticks_txt += " (timed out)"
        detail_surf = self.font.render(ticks_txt, True, COLOR_WHITE)
        self.screen.blit(detail_surf, (rx, ry + 30))

        pygame.display.flip()

        # Wait for keypress or 3 seconds
        waiting = True
        wait_start = pygame.time.get_ticks()
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return
                if event.type == pygame.KEYDOWN:
                    waiting = False
            if pygame.time.get_ticks() - wait_start > 3000:
                waiting = False
            self.clock.tick(30)

    def close(self) -> None:
        # Minimize first — on macOS, pygame.quit() alone can leave a
        # ghost window if the main thread immediately goes CPU-bound.
        try:
            pygame.display.iconify()
            pygame.event.pump()
        except pygame.error:
            pass
        pygame.display.quit()
        pygame.quit()
