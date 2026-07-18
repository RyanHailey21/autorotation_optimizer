# Software architecture

## Purpose

The repository separates the numerical hot path, workflow orchestration, and
report generation so each can be reused and tested independently. The C++ core
owns aerodynamic interpolation, mass properties, transient simulation,
objective scoring, and continuous optimization. Python owns offline polar
generation, concurrency, content-addressed caching, and report assembly.

The terminal output is intended for people. Programmatic consumers must use the
versioned JSON result written by `--result-json`.

## Component map

| Component | Responsibility |
| --- | --- |
| `cpp/include/types.hpp` | Physical state, geometry, simulation, objective, and optimization configuration types |
| `AeroClient` | Validate and load one regular polar grid; interpolate in alpha, log Reynolds number, and Mach |
| `RotorModel` | Compute printed mass/inertia and run the transient axial BEMT simulation |
| `optimizer.hpp` | Decode the five-variable design vector, score simulation results, and run NLopt |
| `result_io.hpp` | Write transient CSV and schema-versioned optimization JSON |
| `main.cpp` | Parse CLI arguments, connect core components, and print the human-readable record |
| `aero_service.py` | Generate offline NeuralFoil or explicit fallback polar tables |
| `run_optimization.py` | Build, cache, parallelize per-airfoil runs, rank results, and invoke reporting |
| `optimizer_result.py` | Normalize versioned JSON; retain terminal-text parsing for compatibility |
| `reporting.py` | Produce offline HTML, summary JSON, leaderboard CSV, and the best trace |

The `autorotation_core` CMake target contains the reusable C++ implementation.
`autorotation_opt` is a thin executable linked to that target.

## Execution flow

The complete `run.sh` workflow performs these stages:

1. Validate and normalize the requested airfoil list.
2. Generate or reuse one polar table per airfoil.
3. Incrementally configure and build the C++ targets.
4. Run independent geometry optimizations concurrently.
5. Read each optimizer's versioned JSON result and rank by objective.
6. Copy the winning polar to `data/aero_polar.csv`.
7. Generate or reuse the offline engineering report.

NeuralFoil, subprocess execution, file I/O, and telemetry collection are kept
outside objective evaluations. `RotorModel::simulate()` instantiates the
compile-time no-trace path; `simulate_with_trace()` is called only for a final
optimized geometry.

## Configuration ownership

Defaults used by the production case are explicit C++ values in
`cpp/include/types.hpp`:

- `RotorGeometry`: blade count, discretization, planform, pitch, and airfoil;
- `Environment`: density, viscosity, and gravity;
- `SimulationConfig`: mass/manufacturing assumptions, initial conditions,
  integration settings, bearing torque, and validity limits;
- `ObjectiveConfig`: rotor-speed, extrapolation, induction-failure, and invalid
  result penalties; and
- `OptimizationConfig`: bounds, initial design, evaluation limit, tolerance,
  and objective configuration.

Changing any value that can affect an optimized result changes the linked
executable and therefore invalidates the per-airfoil optimization cache. New
configuration values must also be included in the JSON engineering record when
they are needed to reproduce or interpret a result.

## Structured result contract

Request structured output with:

```bash
./build/autorotation_opt --root . --polar data/aero_polar.csv \
  --trace trace.csv --result-json result.json --quiet
```

The root JSON object currently has `schema_version: 1` and these sections:

| Field | Contents |
| --- | --- |
| `backend`, `airfoil` | Polar provenance identifiers |
| `status`, `evaluations`, `objective` | Optimization outcome |
| `geometry` | Optimized design, blade count, and radial discretization |
| `simulation` | Validity, performance, mass, confidence, and induction diagnostics |
| `simulation_config` | Configuration values required by the report |
| `optimization_config` | Optimizer identity, limits, tolerance, and radius bounds |

All quantities use SI base units in this artifact, with units encoded in field
names. Mass is stored in kilograms and angular speed in radians per second.
`optimizer_result.parse_result_json()` converts selected quantities to the
display units expected by reporting.

Schema changes must be deliberate:

1. preserve the meaning of existing version-1 fields;
2. increment `schema_version` for an incompatible change;
3. update `write_result_json()` and `parse_result_json()` together;
4. add contract tests for the new version; and
5. invalidate the optimization cache version if old artifacts cannot be used.

Do not add a second ad hoc parser in orchestration or reporting. Human-readable
terminal labels may evolve without affecting internal consumers.

## Cache contracts

Generated artifacts live under `.cache/` and are not source files.

- Polar keys cover the backend, airfoil, generator contents, generated output
  hash, and relevant Python package versions.
- Optimization keys cover the linked executable and polar contents. Because
  C++ configuration defaults compile into the executable, configuration changes
  invalidate these entries.
- Report keys cover normalized metrics, trace contents, report-generator
  contents, Plotly version, and backend.

Cache writes for polars use a temporary file followed by an atomic replacement.
When adding a result-changing input, extend the appropriate key and its contract
test in `python/test_run_optimization.py`.

## Verification tiers

Use the smallest tier that covers the change, then expand for higher-risk work.

### Unit checks

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure
python3 -m unittest discover -s python -p 'test_*.py'
```

C++ tests cover polar interpolation and confidence, objective penalties,
geometry validation, printed mass/inertia behavior, and aerodynamic-table
identity. Python tests cover text/JSON contracts and cache invalidation.

### Tracked-polar smoke test

```bash
./build/autorotation_opt --root . --polar data/aero_polar.csv \
  --trace /tmp/autorotation-trace.csv \
  --result-json /tmp/autorotation-result.json --quiet
```

This is deterministic enough to compare with the regression reference in
`ENGINEERING_GOALS.md`, but that reference is not a physical validation target.

### Workflow integration

Use a single explicit airfoil before the full production set:

```bash
bash ./run.sh --backend fallback --airfoils NACA0012 --jobs 1 --force
bash ./run.sh --backend fallback --airfoils NACA0012 --jobs 1
```

The second run should report cached polar, optimization, and report reuse. The
fallback backend is appropriate for workflow tests only, not engineering
conclusions.

### Full case

Run `bash ./run.sh` for changes to model physics, the production search,
caching, concurrency, or final reports. Inspect finite values, solver status,
penalties, and machine-readable artifacts for every candidate.

## Extension guidance

- Add new physical state and assumptions to the typed C++ configuration rather
  than introducing file-local constants in `main.cpp`.
- Add reusable model behavior to `autorotation_core`; keep CLI-specific
  presentation in `main.cpp`.
- Test objective terms independently through `score_simulation()` before
  relying on expensive optimization regressions.
- Test mass-model changes through `RotorModel::mass_properties()`.
- Keep the C++ result schema independent from Plotly and HTML presentation.
- Document physical changes in `ENGINEERING_GOALS.md`; document component or
  data-contract changes here; document user-visible commands in `README.md`.
