# Evolution Tank

A 2D tank battle simulation where strategies evolve through natural selection. Teams of autonomous tanks fight in arenas with terrain, fog of war, and friendly fire. Winning strategies are selected, mutated, and crossed over across generations — no human-designed AI, just evolution.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

## What happens

1. Two populations of **behavior tree** strategies are randomly generated.
2. Strategies are paired against each other in **simulated battles** across different arena layouts.
3. Each strategy is scored on damage dealt, kills, survival, ammo efficiency, and team coordination — but survival only counts if you actually fight (no camping).
4. The best strategies are **selected, crossed over, and mutated** to produce the next generation.
5. Over many generations, complex behaviors emerge: flanking, focus fire, retreat-and-repair, coordinated signals.

The simulation is fully deterministic given a seed, and runs headless or with a Pygame viewer.

## Quick start

```bash
# Clone and install
git clone https://github.com/ettoreferranti/evolution_tank.git
cd evolution_tank
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run evolution (with battle replays every 10 generations)
python -m evolution_tank --evolve --seed 42

# Fast mode (smaller population, fewer generations — good for testing)
python -m evolution_tank --evolve --fast --seed 42

# Headless (no visualization)
python -m evolution_tank --evolve --headless --seed 42

# Custom settings
python -m evolution_tank --evolve --generations 200 --population 50
```

## What you'll see

During evolution, the terminal shows fitness stats per generation:

```
Gen   0 | T0: best= 142.5 mean=  58.3 comp=2L/2M/1H | T1: best= 201.4 mean=  71.6 comp=1L/0M/2H
Gen   1 | T0: best= 983.1 mean= 475.7 comp=1L/1M/1H | T1: best= 876.9 mean= 546.1 comp=1L/0M/2H
```

At configured intervals, a Pygame window opens to replay the best-vs-best match:

- **Space** — pause/unpause
- **1-9, 0** — set speed (1x to 10x)
- **+/-** — adjust speed
- **F** — cycle fog of war (off / Team 0 / Team 1)
- **Q** — close replay and continue evolution

## How it works

### Tank types

Three tank types with different trade-offs — all stats are [configurable](config/settings.yaml):

| | Light | Medium | Heavy |
|---|---|---|---|
| HP | 50 | 100 | 200 |
| Armor | 5 | 15 | 30 |
| Speed | 5.0 | 3.5 | 2.0 |
| Damage | 20 | 45 | 100 |
| Visibility | 250 | 200 | 150 |
| Reload (s) | 8 | 12 | 20 |

**Team composition evolves** alongside behavior — evolution discovers whether all-light swarms, heavy-core formations, or balanced mixes work best.

### Strategy: behavior trees

Each strategy is a behavior tree that controls every tank on the team. Trees are built from:

- **Composites**: `Selector` (try children until one succeeds), `Sequence` (run children until one fails)
- **Conditions**: `EnemyVisible`, `HealthBelow`, `AmmoBelow`, `InRange`, `UnderFire`, `AllyNearby`, `NearCover`
- **Actions**: `AimAt`, `Fire`, `MoveToward`, `MoveAway`, `Patrol`, `SeekCover`, `Repair`, `Signal`, `MoveToSignal`

Every numeric parameter (thresholds, distances, ranges) is a gene that mutates. The tree structure itself also evolves through insertion, deletion, swap, and replacement mutations.

### Fitness

Strategies are scored on multiple weighted components:

| Component | Weight | Notes |
|---|---|---|
| Win | 10.0 | Flat bonus for winning |
| Damage dealt | 1.0 | Enemy damage only |
| Friendly fire | -2.0 | Double penalty |
| Damage taken | -0.5 | Penalty for getting hit |
| Survival | 0.1 | Proportional to kills — no reward for passive camping |
| Ammo efficiency | 2.0 | Hit/shot ratio |
| Team coordination | 1.0 | Signal usage |

All weights are configurable in `config/settings.yaml`.

### Evolution

- **Tournament selection** with configurable tournament size
- **Elitism** — top-K strategies preserved unchanged
- **Crossover** — subtree swap between parents
- **Mutation** — parameter perturbation (Gaussian noise) + structural changes
- **Two independent populations** co-evolve against each other (arms race dynamics)
- Matches run in **parallel** across CPU cores

### Arena

Battles rotate through arena presets to prevent overfitting to one layout:

- **default** — mixed terrain with walls, mud patches, and roads
- **open** — wide open field, nowhere to hide
- **maze** — tight corridors, lots of cover
- **corridors** — long lanes with intersections

Terrain affects movement speed and line of sight. Walls block both movement and projectiles.

## Configuration

Everything is configurable via [`config/settings.yaml`](config/settings.yaml). Key sections:

- `arena` — size, presets, terrain types
- `tank_types` — stats for light/medium/heavy
- `match` — team size, tick limit, spawn rules
- `evolution` — population size, mutation rates, selection pressure
- `fitness` — component weights
- `fog_of_war` — toggle, team vision sharing
- `combat` — friendly fire toggle
- `visualization` — window size, replay frequency, colors

Pass a custom config with `--config path/to/custom.yaml` — it merges with defaults, so you only need to specify what you want to override.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed system design with diagrams covering the simulation engine, evolution loop, behavior trees, communication system, and data flow.

## Project structure

```
evolution_tank/
├── config/settings.yaml         # All configurable parameters
├── src/evolution_tank/
│   ├── simulation/              # Arena, physics, combat, fog of war, match runner
│   ├── tanks/                   # Tank model and types
│   ├── strategy/                # Behavior trees, actions, conditions, serialization
│   ├── evolution/               # Selection, mutation, crossover, fitness, engine
│   ├── visualization/           # Pygame renderer
│   ├── evolve.py                # Evolution loop with replay support
│   └── config.py                # Settings loader and validation
├── tests/                       # 253 tests mirroring src/ structure
├── docs/                        # Architecture and test plan
└── BACKLOG.txt                  # Feature backlog with status
```

## Tests

```bash
python -m pytest tests/           # Run all tests
python -m pytest tests/ -v        # Verbose output
python -m pytest tests/ --cov     # With coverage
```

## Contributing

Contributions are welcome! The [BACKLOG.txt](BACKLOG.txt) has a prioritized list of features with status markers. Good places to start:

- **Analytics pipeline** (Phase 4) — fitness CSV export, diversity metrics, lineage tracking, win-rate matrices
- **Convergence detection** — auto-stop when fitness plateaus
- **Battle replay system** — record and replay full matches
- **New game modes** — capture the flag, energy economy

The codebase follows a few conventions:
- No hardcoded values — everything goes through `Config`
- All randomness flows through seeded `random.Random` instances
- The simulation runs identically with or without visualization
- Type hints on all public functions

## License

MIT
