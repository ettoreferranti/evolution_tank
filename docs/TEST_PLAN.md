# Evolution Tank — Test Plan

Last updated: 2026-04-30

## Testing Strategy

| Level          | Tool    | Purpose                                    |
|----------------|---------|--------------------------------------------|
| Unit tests     | pytest  | Individual components in isolation          |
| Integration    | pytest  | Subsystem interactions                      |
| Simulation     | Custom  | Statistical properties of evolution         |
| Visual / manual| Pygame  | Rendering correctness, UX                   |

All automated tests must pass before any merge to main.
Tests mirror the `src/` directory structure under `tests/`.

---

## 1. Configuration System

### Unit Tests
- [ ] Load valid YAML, all fields populated correctly
- [ ] Missing fields fall back to defaults
- [ ] Invalid values (negative HP, team size 0, etc.) raise validation error
- [ ] Config object is immutable after creation
- [ ] Unknown keys in YAML are warned/ignored, not silently accepted

### Integration Tests
- [ ] Simulation runs with default config (no YAML file)
- [ ] Simulation runs with partial config (some overrides)
- [ ] Simulation runs with full custom config

---

## 2. Arena / Map

### Unit Tests
- [ ] Map loads from preset name correctly
- [ ] Map respects min/max size bounds
- [ ] All terrain types parsed correctly
- [ ] Invalid terrain character raises error
- [ ] Map boundary is always wall (tanks can't leave)

### Integration Tests
- [ ] Tank speed is modified by terrain (mud slows, road speeds)
- [ ] Walls block movement
- [ ] Walls block projectiles
- [ ] Walls block line of sight

---

## 3. Tank Model

### Unit Tests
- [ ] Tank type configs loaded correctly for light/medium/heavy
- [ ] HP cannot exceed max_hp
- [ ] Ammo cannot exceed max_ammo
- [ ] Ammo decrements on fire
- [ ] Cannot fire when ammo is 0
- [ ] Cannot fire during reload cooldown
- [ ] Reload timer resets after firing
- [ ] Repair: tank enters REPAIRING state, cannot move or fire
- [ ] Repair: HP restored to full after repair_time elapses
- [ ] Repair: tank is vulnerable (can take damage) while repairing
- [ ] Repair: NOT interruptible — continues even when hit (unless destroyed)
- [ ] Repair: tank destroyed during repair sets state to DESTROYED
- [ ] Repair: cannot cancel repair once started
- [ ] Destroyed tanks cannot act

### Integration Tests
- [ ] Light tank faster than medium, medium faster than heavy (on same terrain)
- [ ] Heavy tank does more damage than light
- [ ] All three types function in same battle

---

## 4. Physics & Movement

### Unit Tests
- [ ] Position updates correctly given velocity and timestep
- [ ] Acceleration increases velocity up to max speed
- [ ] Deceleration when no input, tank stops
- [ ] Turn rate limits heading change per tick
- [ ] Turret rotation independent of hull, respects rotation speed limit

### Integration Tests
- [ ] Tank-tank collision: tanks stop, no overlap, no damage
- [ ] Tank-wall collision: tank stops at wall edge
- [ ] Terrain speed modifier applies correctly
- [ ] Tank cannot move through other tanks

---

## 5. Combat System

### Unit Tests
- [ ] Projectile spawns at turret position with correct direction
- [ ] Projectile travels at configured speed (per tank type)
- [ ] Shell speed differs between light/medium/heavy
- [ ] Projectile despawns after max range
- [ ] Damage calculation: `max(0, shot_damage - target_armor)`
- [ ] Tank destroyed when HP reaches 0
- [ ] Friendly fire: projectile damages allied tank
- [ ] Lead calculation: aim_at action computes intercept based on target velocity + shell speed

### Integration Tests
- [ ] Projectile blocked by wall (does not pass through)
- [ ] Projectile hits correct tank (nearest in path)
- [ ] Multiple projectiles in flight simultaneously
- [ ] Tank firing while moving: projectile direction matches turret, not hull

---

## 6. Fog of War

### Unit Tests
- [ ] Tank only sees enemies within visibility range
- [ ] Wall blocks line of sight (raycast)
- [ ] Sensor data correct: angle, distance, heading, turret direction, type
- [ ] Enemy HP NOT included in sensor data
- [ ] Enemy ammo NOT included in sensor data

### Integration Tests
- [ ] Team vision sharing: tank A sees enemy, tank B (out of range) receives info
- [ ] Vision updates correctly as tanks move
- [ ] Tank behind wall is invisible even if within range

---

## 7. Match System

### Unit Tests
- [ ] Match ends when one team eliminated (last standing)
- [ ] Match ends at time limit
- [ ] Tiebreaker: most damage dealt wins
- [ ] Best-of-N: correct team wins series
- [ ] Free-for-all mode: every tank is own team
- [ ] Team sizes between 1 and 10 accepted
- [ ] Team size outside bounds rejected

### Integration Tests
- [ ] Full match runs to completion with 2 teams
- [ ] Full match runs to completion in free-for-all
- [ ] Match result records all relevant data (damage, kills, survival time)
- [ ] Spawn positions on opposite sides of map
- [ ] Spawn positions never on impassable terrain
- [ ] Spawn positions have minimum separation between tanks

---

## 7b. Seed Strategies & Generation 0

### Unit Tests
- [ ] Random behavior tree generation produces valid trees
- [ ] Seed strategies load from file correctly
- [ ] Mix mode: seeds + random fill produces correct population size
- [ ] Seed strategy file with invalid format raises error

### Integration Tests
- [ ] Generation 0 with all-random produces diverse population
- [ ] Generation 0 with seeds: seeded strategies present in initial battles
- [ ] Same seed produces identical generation 0

---

## 8. Behavior Trees

### Unit Tests
- [ ] Selector node: tries children left-to-right, returns first success
- [ ] Sequence node: runs children left-to-right, stops on first failure
- [ ] Condition nodes evaluate correctly against sensor data
- [ ] Action nodes produce correct tank commands
- [ ] Tree serialization → deserialization roundtrip preserves structure
- [ ] Tree with no valid action returns idle/no-op

### Integration Tests
- [ ] Simple strategy (always move forward + fire) controls tank correctly
- [ ] Strategy reacts to enemy visibility (engages when sees enemy)
- [ ] Strategy reacts to low HP (triggers repair)
- [ ] Signal action sends signal received by allies

---

## 9. Communication

### Unit Tests
- [ ] Signal created with correct type and position
- [ ] Signal received by allies within visibility range
- [ ] Signal NOT received by enemies
- [ ] Signal NOT received by allies out of range
- [ ] All signal types handled

### Integration Tests
- [ ] Tank sends ENEMY_SPOTTED, ally reacts by moving toward
- [ ] Multiple signals in one tick handled correctly

---

## 10. Evolution Engine

### Unit Tests
- [ ] Tournament selection picks highest-fitness from k random candidates
- [ ] Elitism preserves top-K strategies unchanged
- [ ] Parameter mutation: values change within expected distribution
- [ ] Parameter mutation: respects bounds (no negative HP thresholds, etc.)
- [ ] Crossover produces valid tree (no orphan nodes)
- [ ] Structural mutation: insert produces valid tree
- [ ] Structural mutation: delete produces valid tree
- [ ] Structural mutation: swap produces valid tree
- [ ] Population size remains constant across generations
- [ ] Seeded RNG produces identical results
- [ ] Composition mutation: shifts one tank type to another, sum preserved
- [ ] Composition crossover: blended composition sums to team_size
- [ ] Composition vector always sums to team_size after any operation

### Integration Tests
- [ ] Full generation cycle: battle → score → select → mutate → next gen
- [ ] Fitness improves (or does not regress) over 10 generations (statistical)
- [ ] Independent team populations do not cross-contaminate
- [ ] Population diversity maintained (not all identical after N generations)

---

## 11. Analytics

### Unit Tests
- [ ] Fitness logger records correct values
- [ ] CSV export format is valid and parseable
- [ ] Lineage tracker records parent-child relationships
- [ ] Strategy diversity metric computes correctly for known inputs

### Integration Tests
- [ ] Full run produces expected output files
- [ ] Fitness curve data matches actual match outcomes
- [ ] Lineage tree is complete (no orphaned strategies)

---

## 12. Visualization

### Manual Tests (checklist)
- [ ] Map renders with correct terrain colors
- [ ] Tanks render at correct positions with correct heading
- [ ] Turret direction visible and distinct from hull
- [ ] HP bars display and update on damage
- [ ] Projectiles visible in flight
- [ ] Fog of war overlay hides unseen areas
- [ ] Fog of war toggle cycles: off → Team A → Team B → omniscient
- [ ] Team perspective toggle works correctly
- [ ] Speed controls work (pause, 1x, 2x, 4x, max)
- [ ] Destroyed tanks visually distinct
- [ ] UI overlay shows correct match info
- [ ] Generation counter updates between matches
- [ ] No visual glitches at map edges
- [ ] Performance acceptable with max team size (10v10)

---

## 13. Determinism & Reproducibility

### Tests
- [ ] Same seed + same config + same strategies → identical battle outcome
- [ ] Same seed + same config → identical evolution trajectory over 5 generations
- [ ] Changing seed produces different results

---

## 14. Performance Benchmarks (non-blocking)

Track but do not gate on these:
- [ ] Single battle (5v5) completes in < 1 second headless
- [ ] Full generation (100 strategies, best-of-3) completes in < 60 seconds headless
- [ ] 100 generations complete in < 2 hours headless
- [ ] Visualization maintains 30+ FPS at 1x speed with 10v10
