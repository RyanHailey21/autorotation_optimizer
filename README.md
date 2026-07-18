# Autorotation Rotor Optimizer

C++20 optimizer for a three-bladed autorotating rotor carrying a 100 g drone
body and electronics package.

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
- NumPy, NeuralFoil, and AeroSandbox

Ubuntu/WSL setup:

```bash
sudo apt install cmake ninja-build g++ libnlopt-cxx-dev python3-venv
python3 -m venv .venv
.venv/bin/pip install --requirement requirements.txt
```

## Run

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

Useful PowerShell options:

```powershell
.\run.ps1 -Force
.\run.ps1 -RefreshPolar
.\run.ps1 -Jobs 1
.\run.ps1 -Backend fallback
.\run.ps1 -Airfoils NACA0012,NACA2409,NACA4409
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

The executable clamps aerodynamic queries outside the polar grid and assigns
zero confidence, which feeds the objective penalty. At startup it reports the
polar backend and airfoil.

## Current limitations

This is not yet a validated flight-dynamics model. The BEMT solve is
quasi-steady and axial-only. Remaining high-value work includes:

1. verify force and torque signs with hand-calculated blade elements;
2. compare fixed-RPM loads against an independent BEMT implementation;
3. validate axial induction and add tangential wake induction;
4. add dynamic stall or validated 360-degree section data;
5. add body drag, structural constraints, hub properties, and deployment; and
6. validate RPM and descent speed with instrumented drop tests.
