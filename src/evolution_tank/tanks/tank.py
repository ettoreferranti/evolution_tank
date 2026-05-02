"""Tank model — types, state machine, properties."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from evolution_tank.simulation.arena import Vector2

if TYPE_CHECKING:
    from evolution_tank.config import TankTypeConfig


class TankType(Enum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


class TankState(Enum):
    ACTIVE = "active"
    REPAIRING = "repairing"
    DESTROYED = "destroyed"


@dataclass
class Projectile:
    position: Vector2
    velocity: Vector2
    damage: int
    owner_id: int
    team_id: int
    distance_traveled: float = 0.0
    max_range: float = 300.0
    active: bool = True

    def update(self, dt: float) -> None:
        if not self.active:
            return
        step = self.velocity * dt
        self.position = self.position + step
        self.distance_traveled += step.length()
        if self.distance_traveled >= self.max_range:
            self.active = False


@dataclass
class Tank:
    """A single tank in the simulation."""

    id: int
    team_id: int
    tank_type: TankType
    type_config: TankTypeConfig

    # Spatial
    position: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))
    velocity: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))
    heading: float = 0.0           # degrees, 0 = east
    turret_angle: float = 0.0     # degrees, absolute (not relative to hull)

    # State
    state: TankState = TankState.ACTIVE
    hp: int = 0
    max_hp: int = 0
    ammo: int = 0
    max_ammo: int = 0

    # Timers
    reload_timer: float = 0.0     # seconds remaining until can fire
    repair_timer: float = 0.0     # seconds remaining until repair complete

    # Stats tracking (for fitness evaluation)
    damage_dealt: float = 0.0       # damage to enemies only
    friendly_damage_dealt: float = 0.0  # damage to own team (friendly fire)
    damage_taken: float = 0.0
    shots_fired: int = 0
    shots_hit: int = 0
    kills: int = 0
    signals_sent: int = 0
    signals_responded_to: int = 0
    survival_ticks: int = 0

    def __post_init__(self) -> None:
        if self.hp == 0:
            self.hp = self.type_config.hp
            self.max_hp = self.type_config.hp
        if self.ammo == 0:
            self.ammo = self.type_config.ammo
            self.max_ammo = self.type_config.ammo

    @property
    def is_alive(self) -> bool:
        return self.state != TankState.DESTROYED

    @property
    def is_active(self) -> bool:
        return self.state == TankState.ACTIVE

    @property
    def is_repairing(self) -> bool:
        return self.state == TankState.REPAIRING

    @property
    def speed(self) -> float:
        return self.velocity.length()

    @property
    def can_fire(self) -> bool:
        return (
            self.is_active
            and self.ammo > 0
            and self.reload_timer <= 0.0
        )

    @property
    def can_repair(self) -> bool:
        return self.is_active and self.hp < self.max_hp

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def fire(self) -> Projectile | None:
        """Attempt to fire. Returns a Projectile if successful, None otherwise."""
        if not self.can_fire:
            return None

        self.ammo -= 1
        self.shots_fired += 1
        self.reload_timer = self.type_config.reload_time

        direction = Vector2.from_angle(self.turret_angle)
        proj_velocity = direction * self.type_config.projectile_speed

        return Projectile(
            position=self.position + direction * 10,  # spawn slightly ahead of turret
            velocity=proj_velocity,
            damage=self.type_config.damage,
            owner_id=self.id,
            team_id=self.team_id,
            max_range=self.type_config.projectile_range,
        )

    def start_repair(self) -> bool:
        """Begin repair. Returns True if repair started."""
        if not self.can_repair:
            return False
        self.state = TankState.REPAIRING
        self.repair_timer = self.type_config.repair_time
        self.velocity = Vector2(0.0, 0.0)  # Stop moving
        return True

    def take_damage(self, raw_damage: int) -> int:
        """Apply damage after armor. Returns actual damage dealt."""
        if not self.is_alive:
            return 0
        effective = max(0, raw_damage - self.type_config.armor)
        self.hp -= effective
        self.damage_taken += effective
        if self.hp <= 0:
            self.hp = 0
            self.state = TankState.DESTROYED
            self.velocity = Vector2(0.0, 0.0)
        return effective

    def record_hit(self) -> None:
        """Record that a shot from this tank hit a target."""
        self.shots_hit += 1

    def record_kill(self) -> None:
        """Record that this tank killed another."""
        self.kills += 1

    def record_damage_dealt(self, amount: float, friendly: bool = False) -> None:
        if friendly:
            self.friendly_damage_dealt += amount
        else:
            self.damage_dealt += amount

    # ------------------------------------------------------------------
    # Tick update
    # ------------------------------------------------------------------

    def update_timers(self, dt: float) -> None:
        """Update reload and repair timers."""
        if not self.is_alive:
            return

        self.survival_ticks += 1

        # Reload
        if self.reload_timer > 0:
            self.reload_timer = max(0.0, self.reload_timer - dt)

        # Repair
        if self.is_repairing:
            self.repair_timer -= dt
            if self.repair_timer <= 0:
                self.hp = self.max_hp
                self.repair_timer = 0.0
                self.state = TankState.ACTIVE

    # ------------------------------------------------------------------
    # Movement helpers (used by physics system)
    # ------------------------------------------------------------------

    def desired_heading_delta(self, target_heading: float, dt: float) -> float:
        """Compute clamped heading change toward target, respecting turn rate."""
        diff = (target_heading - self.heading + 180) % 360 - 180
        max_turn = self.type_config.turn_rate * dt
        return max(-max_turn, min(max_turn, diff))

    def desired_turret_delta(self, target_angle: float, dt: float) -> float:
        """Compute clamped turret rotation toward target angle."""
        diff = (target_angle - self.turret_angle + 180) % 360 - 180
        max_rot = self.type_config.turret_rotation_speed * dt
        return max(-max_rot, min(max_rot, diff))

    @staticmethod
    def compute_lead_angle(
        shooter_pos: Vector2,
        target_pos: Vector2,
        target_vel: Vector2,
        projectile_speed: float,
    ) -> float | None:
        """Compute the angle to aim at to hit a moving target.

        Uses quadratic solution for intercept point.
        Returns angle in degrees, or None if no solution.
        """
        dp = target_pos - shooter_pos
        a = target_vel.length_sq() - projectile_speed * projectile_speed
        b = 2 * dp.dot(target_vel)
        c = dp.length_sq()

        discriminant = b * b - 4 * a * c
        if abs(a) < 1e-10:
            # Target and projectile same speed — linear solution
            if abs(b) < 1e-10:
                return None
            t = -c / b
            if t < 0:
                return None
        else:
            if discriminant < 0:
                return None
            sqrt_d = math.sqrt(discriminant)
            t1 = (-b + sqrt_d) / (2 * a)
            t2 = (-b - sqrt_d) / (2 * a)
            # Pick smallest positive t
            candidates = [t for t in (t1, t2) if t > 0]
            if not candidates:
                return None
            t = min(candidates)

        intercept = target_pos + target_vel * t
        aim = intercept - shooter_pos
        return aim.angle()
