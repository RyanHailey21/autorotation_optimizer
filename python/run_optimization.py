#!/usr/bin/env python3
"""Build and run the geometry optimizer across a cached NACA airfoil family."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from optimizer_result import parse_result_json


ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".cache"
POLAR_CACHE = CACHE_ROOT / "polars"
RUN_CACHE = CACHE_ROOT / "runs"
REPORT_DIR = ROOT / "reports" / "latest"
DEFAULT_POLAR = ROOT / "data" / "aero_polar.csv"
GENERATOR = ROOT / "python" / "aero_service.py"
REPORT_GENERATOR = ROOT / "python" / "reporting.py"
BUILD_DIR = ROOT / "build"
EXECUTABLE = BUILD_DIR / "autorotation_opt"
DEFAULT_AIRFOILS = [
    f"NACA{camber}{position}{thickness:02d}"
    for camber, position in ((0, 0), (2, 4), (4, 4), (6, 4))
    for thickness in (9, 12, 15, 18)
]


@dataclass(frozen=True)
class SolverConfiguration:
    body_mass_kg: float = 0.100
    release_height_m: float = 20.0
    maximum_evaluations: int = 500
    relative_x_tolerance: float = 1.0e-3
    radius_min_m: float = 0.12
    radius_max_m: float = 0.45
    omega_penalty_threshold_rad_s: float = 2500.0


def solver_arguments(configuration: SolverConfiguration) -> list[str]:
    return [
        "--body-mass-kg", str(configuration.body_mass_kg),
        "--release-height-m", str(configuration.release_height_m),
        "--max-evaluations", str(configuration.maximum_evaluations),
        "--relative-x-tolerance", str(configuration.relative_x_tolerance),
        "--radius-min-m", str(configuration.radius_min_m),
        "--radius-max-m", str(configuration.radius_max_m),
        "--omega-penalty-threshold-rad-s",
        str(configuration.omega_penalty_threshold_rad_s),
    ]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, capture: bool = False,
        label: str | None = None) -> subprocess.CompletedProcess[str]:
    if os.environ.get("AUTOROTATION_VERBOSE_COMMANDS") == "1":
        print("+", shlex.join(command), flush=True)
    elif label:
        print(label, flush=True)
    return subprocess.run(
        command, cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def desired_polar_stamp(backend: str, airfoil: str) -> dict[str, str]:
    stamp = {
        "backend": backend,
        "airfoil": airfoil,
        "generator_sha256": file_sha256(GENERATOR),
        "numpy_version": package_version("numpy"),
    }
    if backend == "neuralfoil":
        stamp["neuralfoil_version"] = package_version("neuralfoil")
        stamp["aerosandbox_version"] = package_version("aerosandbox")
    return stamp


def polar_paths(backend: str, airfoil: str) -> tuple[Path, Path]:
    stem = f"{backend}-{airfoil}"
    return POLAR_CACHE / f"{stem}.csv", POLAR_CACHE / f"{stem}.json"


def polar_is_cached(polar: Path, stamp_path: Path, desired: dict[str, str]) -> bool:
    if not polar.exists() or not stamp_path.exists():
        return False
    try:
        actual = json.loads(stamp_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    output_hash = actual.pop("output_sha256", None)
    return actual == desired and output_hash == file_sha256(polar)


def prepare_polar(backend: str, airfoil: str, refresh: bool) -> Path:
    from aero_service import generate_table

    desired = desired_polar_stamp(backend, airfoil)
    polar, stamp_path = polar_paths(backend, airfoil)
    if not refresh and polar_is_cached(polar, stamp_path, desired):
        print(f"Using cached {backend} polar for {airfoil}")
        return polar

    POLAR_CACHE.mkdir(parents=True, exist_ok=True)
    temporary = POLAR_CACHE / f"{backend}-{airfoil}.pending.csv"
    try:
        print(f"Generating {backend} polar for {airfoil} ...", flush=True)
        count = generate_table(temporary, airfoil, backend)
        print(f"Wrote {count} points for {airfoil}")
        os.replace(temporary, polar)
    finally:
        temporary.unlink(missing_ok=True)

    desired["output_sha256"] = file_sha256(polar)
    stamp_path.write_text(json.dumps(desired, indent=2, sort_keys=True) + "\n")
    return polar


def build() -> None:
    if not (BUILD_DIR / "CMakeCache.txt").exists():
        run(["cmake", "-S", "cpp", "-B", "build", "-G", "Ninja",
             "-DCMAKE_BUILD_TYPE=Release"], label="Configuring Release build ...")
    run(["cmake", "--build", "build", "-j"], label="Building C++ optimizer ...")


def optimization_key(polar: Path, configuration: SolverConfiguration = SolverConfiguration()) -> str:
    digest = hashlib.sha256()
    digest.update(b"autorotation-run-cache-v4-config-json\0")
    digest.update(file_sha256(EXECUTABLE).encode())
    digest.update(file_sha256(polar).encode())
    digest.update(json.dumps(configuration.__dict__, sort_keys=True).encode())
    return digest.hexdigest()


def report_key(results: list[dict[str, object]], backend: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"autorotation-report-v1\0")
    digest.update(file_sha256(REPORT_GENERATOR).encode())
    digest.update(package_version("plotly").encode())
    digest.update(backend.encode())
    for result in results:
        digest.update(json.dumps(result["metrics"], sort_keys=True).encode())
        digest.update(file_sha256(Path(result["trace_path"])).encode())
    return digest.hexdigest()


def prepare_report(results: list[dict[str, object]], backend: str) -> Path:
    report_path = REPORT_DIR / "report.html"
    stamp_path = REPORT_DIR / "report-key.txt"
    key = report_key(results, backend)
    if report_path.exists() and stamp_path.exists() and stamp_path.read_text().strip() == key:
        print(f"Using cached engineering report: {report_path.relative_to(ROOT)}")
        return report_path

    from reporting import generate_report

    report_path = generate_report(results, REPORT_DIR, backend)
    stamp_path.write_text(key + "\n")
    return report_path


def optimize(polar: Path, force: bool, configuration: SolverConfiguration) -> tuple[str, Path, dict[str, object]]:
    key = optimization_key(polar, configuration)
    result_path = RUN_CACHE / f"{key}.txt"
    trace_path = RUN_CACHE / f"{key}.csv"
    json_path = RUN_CACHE / f"{key}.json"
    if result_path.exists() and trace_path.exists() and json_path.exists() and not force:
        print(f"Using cached optimization for {polar.stem}")
        return result_path.read_text(), trace_path, json.loads(json_path.read_text())

    RUN_CACHE.mkdir(parents=True, exist_ok=True)
    completed = run(
        [str(EXECUTABLE), "--root", str(ROOT), "--polar", str(polar),
         "--trace", str(trace_path), "--result-json", str(json_path), "--quiet",
         *solver_arguments(configuration)],
        capture=True,
        label=f"Running geometry search for {polar.stem.split('-', 1)[-1]} ...",
    )
    output = completed.stdout
    result_path.write_text(output)
    print(f"Cached optimization for {polar.stem}")
    return output, trace_path, json.loads(json_path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("neuralfoil", "fallback"),
                        default="neuralfoil")
    parser.add_argument("--airfoils", nargs="+", default=DEFAULT_AIRFOILS,
                        help="NACA identifiers to compare")
    parser.add_argument("--force", action="store_true",
                        help="rerun every geometry optimization")
    parser.add_argument("--refresh-polar", action="store_true",
                        help="regenerate every requested aerodynamic polar")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1),
                        help="number of airfoil geometry optimizations to run concurrently")
    parser.add_argument("--body-mass-kg", type=float, default=0.100)
    parser.add_argument("--release-height-m", type=float, default=20.0)
    parser.add_argument("--max-evaluations", type=int, default=500)
    parser.add_argument("--relative-x-tolerance", type=float, default=1.0e-3)
    parser.add_argument("--radius-min-m", type=float, default=0.12)
    parser.add_argument("--radius-max-m", type=float, default=0.45)
    parser.add_argument("--omega-penalty-threshold-rad-s", type=float, default=2500.0)
    args = parser.parse_args()

    airfoils = list(dict.fromkeys(name.upper() for name in args.airfoils))
    invalid = [name for name in airfoils if not re.fullmatch(r"NACA\d{4}", name)]
    if invalid:
        parser.error(f"expected four-digit NACA names; invalid: {', '.join(invalid)}")
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    if args.body_mass_kg <= 0 or args.release_height_m <= 0:
        parser.error("mass and release height must be positive")
    if args.max_evaluations < 1 or args.relative_x_tolerance <= 0:
        parser.error("evaluation limit and relative tolerance must be positive")
    if args.radius_min_m <= 0 or args.radius_min_m >= args.radius_max_m:
        parser.error("radius bounds must be positive and increasing")
    if args.omega_penalty_threshold_rad_s <= 0:
        parser.error("rotor-speed penalty threshold must be positive")
    solver_configuration = SolverConfiguration(
        body_mass_kg=args.body_mass_kg,
        release_height_m=args.release_height_m,
        maximum_evaluations=args.max_evaluations,
        relative_x_tolerance=args.relative_x_tolerance,
        radius_min_m=args.radius_min_m,
        radius_max_m=args.radius_max_m,
        omega_penalty_threshold_rad_s=args.omega_penalty_threshold_rad_s,
    )

    polars = [
        prepare_polar(args.backend, airfoil, args.refresh_polar)
        for airfoil in airfoils
    ]
    build()

    print(f"Optimizing {len(airfoils)} airfoils with {args.jobs} concurrent jobs ...")
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        optimized = list(executor.map(
            lambda polar: optimize(polar, args.force, solver_configuration), polars
        ))

    results = []
    for airfoil, polar, (output, trace_path, document) in zip(
        airfoils, polars, optimized
    ):
        metrics = parse_result_json(document)
        results.append({
            "airfoil": airfoil,
            "polar": polar,
            "output": output,
            "trace_path": trace_path,
            "metrics": metrics,
            "objective": metrics["objective"],
            "fall_time": metrics["fall_time_s"],
            "impact_speed": metrics["impact_speed_m_s"],
            "total_mass": metrics["total_mass_g"],
        })

    results.sort(key=lambda result: result["objective"])
    print("\nAirfoil leaderboard (lower objective is better)")
    print("airfoil       objective   fall_s   impact_m/s   mass_g")
    for result in results:
        print(f"{result['airfoil']:<12} {result['objective']:>9.4f} "
              f"{result['fall_time']:>8.3f} {result['impact_speed']:>12.4f} "
              f"{result['total_mass']:>9.3f}")

    best = results[0]
    shutil.copyfile(best["polar"], DEFAULT_POLAR)
    print(f"\nBest airfoil: {best['airfoil']}")
    print(best["output"], end="")
    print(f"Best polar copied to {DEFAULT_POLAR.relative_to(ROOT)}")
    report_path = prepare_report(results, args.backend)
    print(f"Engineering report: {report_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
