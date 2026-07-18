"""Parse the optimizer's stable, human-readable result record.

Keep all consumers of ``autorotation_opt`` output on this module so changes to
the C++ output contract are validated in one place.
"""

from __future__ import annotations

import math
import re
from typing import Any


STATUS_NAMES = {
    1: "SUCCESS",
    2: "STOPVAL_REACHED",
    3: "FTOL_REACHED",
    4: "XTOL_REACHED",
    5: "MAXEVAL_REACHED",
    6: "MAXTIME_REACHED",
}


def field(output: str, name: str) -> str:
    """Return one named value from the optimizer's line-oriented record."""
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", output, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Optimizer output is missing '{name}'")
    return match.group(1).strip()


def number(output: str, name: str) -> float:
    """Return the leading numeric value for a named field, ignoring its unit."""
    value = field(output, name).split()[0]
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(
            f"Optimizer output field '{name}' is not numeric: {value!r}"
        ) from exc


def parse_result(output: str) -> dict[str, float | int | str]:
    """Parse the complete result record consumed by reports and orchestration."""
    status = int(number(output, "Optimization status"))
    omega = number(output, "max omega")
    radius_bounds = field(output, "radius bounds").split()
    if len(radius_bounds) < 2:
        raise RuntimeError("Optimizer output field 'radius bounds' needs two values")

    return {
        "status": status,
        "status_name": STATUS_NAMES.get(status, f"NLOPT_{status}"),
        "airfoil": field(output, "airfoil"),
        "objective": number(output, "objective"),
        "radius_m": number(output, "radius"),
        "root_chord_m": number(output, "root chord"),
        "tip_chord_m": number(output, "tip chord"),
        "root_pitch_rad": number(output, "root pitch"),
        "tip_twist_rad": number(output, "tip twist"),
        "blade_count": int(number(output, "blade count")),
        "rotor_mass_g": number(output, "rotor mass"),
        "body_mass_g": number(output, "body mass"),
        "total_mass_g": number(output, "total mass"),
        "fall_time_s": number(output, "fall time"),
        "impact_speed_m_s": number(output, "impact speed"),
        "max_omega_rad_s": omega,
        "max_rpm": omega * 60.0 / (2.0 * math.pi),
        "mean_prandtl_factor": number(output, "mean tip/root F"),
        "mean_axial_induction": number(output, "mean induction a"),
        "induction_failure_percent": number(output, "induction failed"),
        "release_height_m": number(output, "release height"),
        "time_step_s": number(output, "time step"),
        "radial_elements": int(number(output, "radial elements")),
        "root_cutout_m": number(output, "root cutout"),
        "material_density_kg_m3": number(output, "material density"),
        "infill_fraction": number(output, "infill fraction"),
        "wall_thickness_m": number(output, "wall thickness"),
        "hardware_mass_g": number(output, "hardware mass"),
        "optimizer": field(output, "optimizer"),
        "maximum_evaluations": int(number(output, "max evaluations")),
        "relative_x_tolerance": number(output, "relative x tol"),
        "radius_lower_bound_m": float(radius_bounds[0]),
        "radius_upper_bound_m": float(radius_bounds[1]),
    }


def parse_result_json(document: dict[str, Any]) -> dict[str, float | int | str]:
    """Normalize a versioned optimizer JSON document for reporting consumers."""
    version = document.get("schema_version")
    if version != 1:
        raise RuntimeError(f"Unsupported optimizer result schema version: {version!r}")
    try:
        geometry = document["geometry"]
        simulation = document["simulation"]
        simulation_config = document["simulation_config"]
        optimization_config = document["optimization_config"]
        status = int(document["status"])
        omega = float(simulation["max_omega_rad_s"])
        return {
            "status": status,
            "status_name": STATUS_NAMES.get(status, f"NLOPT_{status}"),
            "airfoil": str(document["airfoil"]),
            "objective": float(document["objective"]),
            "radius_m": float(geometry["radius_m"]),
            "root_chord_m": float(geometry["root_chord_m"]),
            "tip_chord_m": float(geometry["tip_chord_m"]),
            "root_pitch_rad": float(geometry["root_pitch_rad"]),
            "tip_twist_rad": float(geometry["tip_twist_rad"]),
            "blade_count": int(geometry["blade_count"]),
            "rotor_mass_g": float(simulation["rotor_mass_kg"]) * 1000.0,
            "body_mass_g": float(simulation_config["body_mass_kg"]) * 1000.0,
            "total_mass_g": float(simulation["total_mass_kg"]) * 1000.0,
            "fall_time_s": float(simulation["fall_time_s"]),
            "impact_speed_m_s": float(simulation["impact_speed_m_s"]),
            "max_omega_rad_s": omega,
            "max_rpm": omega * 60.0 / (2.0 * math.pi),
            "mean_prandtl_factor": float(simulation["mean_prandtl_factor"]),
            "mean_axial_induction": float(simulation["mean_axial_induction"]),
            "induction_failure_percent": (
                float(simulation["induction_failure_fraction"]) * 100.0
            ),
            "release_height_m": float(simulation_config["release_height_m"]),
            "time_step_s": float(simulation_config["time_step_s"]),
            "radial_elements": int(geometry["radial_elements"]),
            "root_cutout_m": float(geometry["root_cutout_m"]),
            "material_density_kg_m3": float(
                simulation_config["material_density_kg_m3"]
            ),
            "infill_fraction": float(simulation_config["infill_fraction"]),
            "wall_thickness_m": float(simulation_config["wall_thickness_m"]),
            "hardware_mass_g": (
                float(simulation_config["hardware_mass_kg"]) * 1000.0
            ),
            "optimizer": str(optimization_config["optimizer"]),
            "maximum_evaluations": int(
                optimization_config["maximum_evaluations"]
            ),
            "relative_x_tolerance": float(
                optimization_config["relative_x_tolerance"]
            ),
            "radius_lower_bound_m": float(
                optimization_config["radius_lower_bound_m"]
            ),
            "radius_upper_bound_m": float(
                optimization_config["radius_upper_bound_m"]
            ),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Malformed optimizer result JSON: {exc}") from exc
