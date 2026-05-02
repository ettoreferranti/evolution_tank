# Evolution Tank — Project Instructions

## Overview
2D tank battle simulation focused on evolutionary strategy. Autonomous tanks fight in teams; winning strategies are selected, mutated, and evolved across generations.

## Key Principles
- **Everything configurable**: Never hardcode values. All game parameters, evolution settings, and simulation constants must be configurable via the settings file (`config/settings.yaml`). Use sensible defaults.
- **Simulation-first**: The headless simulation engine is the core product. Visualization is a layer on top, never a dependency.
- **Evolutionary integrity**: The evolution loop must be statistically sound. Randomness must be seeded and reproducible.

## Tech Stack
- Python 3.11+
- Pygame (visualization)
- YAML (configuration)
- pytest (testing)

## Project Structure
```
evolution_tank/
├── config/              # Settings and default configurations
├── src/
│   ├── simulation/      # Core simulation engine (physics, combat, map)
│   ├── tanks/           # Tank types, properties, behavior
│   ├── strategy/        # Behavior trees, strategy representation
│   ├── evolution/       # Selection, mutation, population management
│   ├── analytics/       # Fitness tracking, logging, stats
│   └── visualization/   # Pygame rendering, UI
├── tests/               # Mirror of src/ structure
├── docs/                # Architecture, test plan
├── maps/                # Map definitions
└── output/              # Simulation results, logs, lineage data
```

## Commands
- `python -m pytest tests/` — run all tests
- `python -m evolution_tank` — run simulation (reads config/settings.yaml)
- `python -m evolution_tank --headless` — run without visualization
- `python -m evolution_tank --replay <file>` — replay a saved battle (future)

## Conventions
- **Never hardcode values** — all numeric constants, thresholds, sizes, rates, and counts must come from the Config object. If you're about to type a number in game logic, it belongs in settings.yaml instead.
- Type hints on all public functions
- Docstrings only where behavior is non-obvious
- Keep modules small and focused
- Settings accessed through a single `Config` object, never read directly from file in game logic
- Seeded RNG everywhere — all randomness must flow through a seeded generator for reproducibility
