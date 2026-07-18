#!/usr/bin/env python3
"""Generate an offline aerodynamic polar table for the C++ optimizer.

NeuralFoil is invoked only while this tool runs. The optimizer itself loads the
resulting CSV once and performs interpolation in memory.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np


def fallback_coefficients(alpha_deg: np.ndarray, reynolds: np.ndarray,
                          mach: np.ndarray):
    del mach
    alpha = np.deg2rad(alpha_deg)
    re_factor = np.clip(np.log10(np.maximum(reynolds, 1e3) / 1e4) / 2.0, 0.2, 1.0)
    cl_linear = 2.0 * math.pi * alpha * re_factor
    cl = 1.35 * np.tanh(cl_linear / 1.35)
    cd0 = 0.018 + 0.035 * (1.0 - re_factor)
    cd = cd0 + 0.055 * cl**2 + 0.35 * np.sin(alpha) ** 4
    cm = -0.05 * np.ones_like(cl)
    confidence = np.where(
        (reynolds >= 2.0e4) & (np.abs(alpha_deg) <= 25.0), 0.8, 0.35
    )
    return cl, cd, cm, confidence


def neuralfoil_coefficients(airfoil: str, alpha_deg: np.ndarray,
                            reynolds: np.ndarray, mach: np.ndarray):
    try:
        import aerosandbox as asb
        import neuralfoil as nf
    except ImportError as exc:
        raise RuntimeError(
            "NeuralFoil backend requested, but neuralfoil/aerosandbox is not installed"
        ) from exc

    # NeuralFoil 0.3.x is incompressible and has no Mach input. The optimizer's
    # intended rotor envelope is low-subsonic, so values are replicated along
    # the Mach grid while retaining Mach as a table dimension.
    del mach
    result = nf.get_aero_from_airfoil(
        airfoil=asb.Airfoil(airfoil),
        alpha=alpha_deg,
        Re=reynolds,
        model_size="small",
    )

    def flat(name: str, default: float = 0.0):
        value = result.get(name)
        if value is None:
            return np.full_like(alpha_deg, default, dtype=float)
        return np.asarray(value, dtype=float).reshape(-1)

    cl = flat("CL")
    cd = flat("CD")
    cm = flat("CM")
    confidence = flat("analysis_confidence", default=np.nan)
    if np.isnan(confidence).all():
        confidence = np.where(
            (reynolds >= 2.0e4) & (np.abs(alpha_deg) <= 25.0), 0.9, 0.4
        )
    return cl, cd, cm, confidence


def generate_table(output: Path, airfoil: str, backend: str) -> int:
    # This is the intended aerodynamic operating envelope. Values outside it are
    # clamped by C++ and assigned zero confidence rather than extrapolated.
    alpha_axis = np.arange(-90.0, 145.0, 5.0)
    reynolds_axis = np.geomspace(1.0e3, 2.0e6, 13)
    mach_axis = np.array([0.0, 0.1, 0.2, 0.3])
    alpha, reynolds, mach = np.meshgrid(
        alpha_axis, reynolds_axis, mach_axis, indexing="ij"
    )
    shape = alpha.shape
    alpha_flat = alpha.reshape(-1)
    reynolds_flat = reynolds.reshape(-1)
    mach_flat = mach.reshape(-1)

    evaluator = {
        "neuralfoil": neuralfoil_coefficients,
        "fallback": fallback_coefficients,
    }[backend]
    cl, cd, cm, confidence = evaluator(
        airfoil, alpha_flat, reynolds_flat, mach_flat
    ) if backend == "neuralfoil" else evaluator(alpha_flat, reynolds_flat, mach_flat)

    arrays = [np.asarray(value, dtype=float).reshape(shape)
              for value in (cl, cd, cm, confidence)]
    if not all(np.isfinite(value).all() for value in arrays):
        raise RuntimeError(f"{backend} produced non-finite aerodynamic coefficients")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as stream:
        stream.write(f"# backend={backend}\n")
        stream.write(f"# airfoil={airfoil}\n")
        stream.write("# model_size=small\n")
        stream.write("# mach_model=incompressible_replicated\n")
        stream.write("# generated_offline=true\n")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([
            "airfoil", "alpha_deg", "reynolds", "mach",
            "cl", "cd", "cm", "confidence",
        ])
        for ai, alpha_value in enumerate(alpha_axis):
            for ri, reynolds_value in enumerate(reynolds_axis):
                for mi, mach_value in enumerate(mach_axis):
                    writer.writerow([
                        airfoil, f"{alpha_value:.8g}", f"{reynolds_value:.10g}",
                        f"{mach_value:.8g}", f"{arrays[0][ai, ri, mi]:.10g}",
                        f"{arrays[1][ai, ri, mi]:.10g}",
                        f"{arrays[2][ai, ri, mi]:.10g}",
                        f"{np.clip(arrays[3][ai, ri, mi], 0.0, 1.0):.10g}",
                    ])
    return alpha.size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--airfoil", default="NACA2412")
    parser.add_argument(
        "--backend", choices=("neuralfoil", "fallback"), default="neuralfoil",
        help="explicit coefficient source; never falls back automatically",
    )
    args = parser.parse_args()
    count = generate_table(args.output, args.airfoil, args.backend)
    print(f"Wrote {count} {args.backend} polar points to {args.output}")


if __name__ == "__main__":
    main()
