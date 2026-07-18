# Repository guidance

This is an engineering-grade autorotation optimizer, not a tutorial or
prototype. Preserve physical traceability, numerical diagnostics, and
reproducibility when changing it. Read `docs/ENGINEERING_GOALS.md` before
changing the model, objective, design space, or material assumptions. Read
`docs/ARCHITECTURE.md` before changing component boundaries, structured
artifacts, caching, or orchestration.

## Source of truth and commands

- Treat the repository root on WSL as the primary working copy.
- Run the complete workflow from the repository root with `./run.sh`.
- Keep `run.ps1` functional for the Windows copy, but treat WSL/Linux as the
  primary build and execution environment.
- Use Release builds for performance comparisons. Do not benchmark a debug
  build or include polar generation/report rendering in solver timings.

## Architecture and performance

- Keep the optimization and transient BEMT hot path in C++20. NLopt COBYLA is
  the production continuous optimizer unless a deliberate, validated change is
  made.
- NeuralFoil is an offline polar generator only. Never call NeuralFoil, Python,
  subprocesses, or file I/O from an objective evaluation.
- Optimization must query cached, in-memory aerodynamic tables.
- Put reusable C++ behavior in `autorotation_core`; keep `main.cpp` limited to
  command-line parsing, component wiring, and human-readable presentation.
- Use the versioned `--result-json` artifact for programmatic consumers. Do not
  add another parser for human-readable terminal output.
- Keep the local application a thin orchestration and presentation layer. It
  may launch and monitor the workflow but must not implement model physics or
  objective evaluation in Python or JavaScript.
- Validate application configuration at the HTTP boundary and again at the
  command-line/native boundary. Pass subprocess arguments as an array without
  shell interpolation, and include every result-changing value in cache keys.
- Preserve the compile-time no-trace objective path. Collect telemetry only for
  final optimized candidates; reporting must not slow objective evaluations.
- Preserve content-addressed caching for polar generation, builds where
  applicable, per-airfoil optimization, traces, and reports. Cache keys must
  include every input capable of changing the result.
- Independent airfoil optimizations may run concurrently. Results must remain
  deterministic enough to compare and audit.

## Modeling rules

- The rotor has three blades. Do not reinterpret this as three rotors.
- Include blade mass and polar inertia as functions of the candidate geometry.
- Include Prandtl tip and root/hub loss corrections and expose their diagnostics.
- Preserve the axial-induction convergence diagnostics and penalties. Do not
  silently accept a failed annulus solve.
- Aerodynamic extrapolation outside the polar table must remain visible and
  penalized; do not silently clamp with full confidence.
- The fixed drone body/electronics mass is 100 g. Rotor-device mass is added to
  it, not substituted for it.
- Printed blades use Bambu ASA Aero assumptions: 520 kg/m^3 deposited-material
  density, 5% interior infill, and two 0.4 mm walls. Treat the density as a
  provisional engineering assumption until measured from the actual print
  profile.
- Hub, fastener, support, and deployment hardware mass/inertia are zero only
  because measured or CAD-derived values are not yet available. Never describe
  them as physically negligible.

## Optimization scope

- The outer search includes NACA four-digit airfoil identities. The current
  production set is the 16 combinations of 0/2/4/6% camber and 9/12/15/18%
  thickness, with cambered sections at 40% chord.
- For each airfoil, search all five continuous variables: radius, root chord,
  tip chord, root pitch, and tip twist.
- Keep bounds, starting points, optimizer tolerances, evaluation limits, and
  objective penalties explicit and reported. A change to any of them is an
  engineering-model change and must invalidate relevant caches.
- The current objective maximizes simulated fall time with explicit penalties
  for excessive rotor speed, polar extrapolation, and induction failures. Do
  not replace it with an undocumented composite score.

## Reporting and verification

- Report every design variable for every optimized airfoil, not only the winner.
- Use maintained off-the-shelf plotting (currently Plotly) and keep the report
  offline-capable with a local asset bundle.
- Retain machine-readable CSV/JSON outputs and the best-candidate transient
  trace alongside the HTML report.
- Report units, solver status, mass breakdown, maximum rotor speed, Prandtl
  factor, induction, and convergence failures. Do not hide failed or penalized
  cases from the leaderboard.
- Before handing off a change, run focused unit tests and a Release compile.
  Run the tracked-polar smoke test for C++ or integration changes, and `./run.sh`
  for changes affecting the full search, caching, or reports. Confirm reports
  contain finite data and that an unchanged rerun uses cached work.
- Never claim design readiness from optimizer output alone. Physical release
  requires independent analysis and instrumented testing.
- Keep the application loopback-only by default and do not introduce analytics,
  remote assets, external data transfer, or unauthenticated non-local binding.

## Repository hygiene

- Do not commit `.venv`, `build`, `.cache`, or generated `reports` content.
- Preserve user changes in a dirty worktree and avoid broad rewrites unrelated
  to the task.
- Keep dependency versions pinned and CI representative of the WSL/Linux
  production path.
- Update `docs/ARCHITECTURE.md` when component ownership, result schemas, cache
  inputs, or verification commands change.
- Document any new physical assumption, calibration constant, constraint, or
  validation evidence in `docs/ENGINEERING_GOALS.md` and the user-facing README
  where appropriate.
