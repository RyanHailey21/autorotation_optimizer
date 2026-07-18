# Autorotation Rotor Optimizer

Engineering-grade C++20 design optimizer for a three-bladed autorotating rotor
carrying a 100 g drone body and electronics package.

Development rules are in [`AGENTS.md`](AGENTS.md). The full design basis,
assumptions, validation boundaries, and next goals are in
[`docs/ENGINEERING_GOALS.md`](docs/ENGINEERING_GOALS.md). Component boundaries,
structured result contracts, caching, and verification tiers are described in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Model

The transient simulation integrates vertical motion and rotor speed. Each blade
annulus couples NeuralFoil section data to axial momentum using a native C++
BEMT solve with:

- previous-timestep induction warm starts;
- bounded bracketing and bisection;
- Buhl high-induction behavior;
- Prandtl tip and root losses; and
- explicit convergence diagnostics and objective penalties.

NeuralFoil runs only during offline polar generation. Optimization uses
in-memory interpolation over angle of attack, log Reynolds number, and Mach.
NeuralFoil 0.3.x is incompressible, so its coefficients are replicated along
the low-subsonic Mach grid.

The default outer search compares 16 four-digit NACA sections: 0%, 2%, 4%, and
6% camber at 9%, 12%, 15%, and 18% thickness. Cambered sections place maximum
camber at 40% chord. For every airfoil, NLopt independently searches radius,
root chord, tip chord, root pitch, and tip twist.

## Mass model

Total mass includes a fixed 100 g body/electronics package and three printed
blades. Blade mass and polar inertia are recomputed for every geometry using:

- Bambu ASA Aero deposited-material density: 520 kg/m^3;
- 5% interior infill;
- two 0.4 mm walls; and
- thickness-dependent NACA four-digit cross-sectional area.

The density approximates ASA Aero printed near 260 C and should be replaced by
the measured mass-to-volume ratio from the actual print profile. Hub, fastener,
and support mass and inertia are currently zero until measured or supplied from
CAD. Full-case constants are defined in `cpp/include/types.hpp`.

## Requirements

- WSL on Windows
- CMake 3.20+
- Ninja and a C++20 compiler
- NLopt C++
- Python 3.10+
- NumPy, NeuralFoil, AeroSandbox, and Plotly

Ubuntu/WSL setup:

```bash
sudo apt install cmake ninja-build g++ libnlopt-cxx-dev python3-venv
python3 -m venv .venv
.venv/bin/pip install --requirement requirements.txt
```

## Run

### Local application

Launch the local configuration and results application from WSL:

```bash
./run_app.sh
```

Or launch it from PowerShell:

```powershell
.\run_app.ps1
```

The launcher opens `http://127.0.0.1:8765/`. The interface is browser-based but
entirely local: it binds to the loopback interface, runs the existing workflow
and native C++ solver in WSL, and sends no project data to an external service.
It exposes aerodynamic source, airfoil set, concurrency, cache controls, body
mass, release height, radius bounds, evaluation limit, design tolerance, and
the rotor-speed penalty threshold. Runs are asynchronous and can be cancelled;
live logs, the latest result, the full report, and machine-readable artifacts
remain available in the application.

Use `./run_app.sh --no-open --port 9000` to select a port without opening a
browser. Stop the local server with Ctrl+C.

### Command line

From PowerShell in the project directory:

```powershell
.\run.ps1
```

From WSL/Linux:

```bash
bash ./run.sh
```

The runner caches each NeuralFoil polar by generator and dependency version,
uses CMake's incremental build, and caches each optimization by executable and
polar contents. Independent airfoil optimizations run four-at-a-time.

The implementation is split into a reusable C++ `autorotation_core` library, a
thin optimizer CLI, and Python workflow/reporting modules. Internal workflow
consumers use schema-versioned JSON rather than parsing terminal output.

Every run also produces an offline Plotly engineering report at
`reports/latest/report.html` with the optimized rotor planform, airfoil
leaderboard, every design variable for every candidate, transient histories,
solver diagnostics, active constraints, and machine-readable CSV/JSON data.
Telemetry is recorded only for each final optimized design; objective
evaluations use the compile-time no-trace simulation path.

Useful PowerShell options:

```powershell
.\run.ps1 -Force
.\run.ps1 -RefreshPolar
.\run.ps1 -Jobs 1
.\run.ps1 -Backend fallback
.\run.ps1 -Airfoils NACA0012,NACA2409,NACA4409
.\run.ps1 -OpenReport
```

`-Force` repeats geometry optimization, while `-RefreshPolar` regenerates the
aerodynamic tables. The fallback backend is an explicit approximate development
model; it is never selected automatically. Cached files live under `.cache/`.

## Manual operation

Generate one polar:

```bash
.venv/bin/python python/aero_service.py \
  --backend neuralfoil --airfoil NACA2409 --output data/aero_polar.csv
```

Build and run one optimization:

```bash
cmake -S cpp -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/autorotation_opt --root . --polar data/aero_polar.csv
```

For programmatic use, request a versioned result document instead of parsing
terminal text:

```bash
./build/autorotation_opt --root . --polar data/aero_polar.csv \
  --trace trace.csv --result-json result.json --quiet
```

The reusable C++ model, optimizer, and result-I/O APIs are exposed by the
`autorotation_core` CMake target. Run focused tests with:

```bash
ctest --test-dir build --output-on-failure
python3 -m unittest discover -s python -p 'test_*.py'
```

The command-line workflow accepts the same engineering settings used by the
application. For example:

```bash
bash ./run.sh --airfoils NACA0012 NACA2409 --jobs 2 \
  --body-mass-kg 0.12 --release-height-m 25 \
  --radius-min-m 0.15 --radius-max-m 0.50 \
  --max-evaluations 750 --relative-x-tolerance 0.001 \
  --omega-penalty-threshold-rad-s 2500
```

The executable clamps aerodynamic queries outside the polar grid and assigns
zero confidence, which feeds the objective penalty. At startup it reports the
polar backend and airfoil.

## Engineering validation boundaries

The optimizer preserves explicit model and convergence diagnostics, but design
release still requires correlation to independent analysis and physical test.
The current BEMT solve is quasi-steady and axial-only. Remaining validation and
model-extension work includes:

1. verify force and torque signs with hand-calculated blade elements;
2. compare fixed-RPM loads against an independent BEMT implementation;
3. validate axial induction and add tangential wake induction;
4. add dynamic stall or validated 360-degree section data;
5. add body drag, structural constraints, hub properties, and deployment; and
6. validate RPM and descent speed with instrumented drop tests.
