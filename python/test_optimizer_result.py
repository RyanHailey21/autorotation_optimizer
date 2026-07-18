"""Contract tests for optimizer result parsing."""

from __future__ import annotations

import math
import unittest

from optimizer_result import field, number, parse_result, parse_result_json


SAMPLE_OUTPUT = """Loaded neuralfoil polar for NACA2409

Optimization status: 4
airfoil:          NACA2409
objective:        -8.15429
radius:           0.45 m
root chord:       0.0799726 m
tip chord:        0.0386206 m
root pitch:       -0.10691 rad
tip twist:        0.157847 rad
blade count:      3
rotor mass:       66.0147 g
body mass:        100 g
total mass:       166.015 g
fall time:        9.94 s
impact speed:     1.86975 m/s
max omega:        31.8834 rad/s
mean tip/root F:  0.93049
mean induction a: 0.50362
induction failed: 0 %
release height:   20 m
time step:        0.01 s
radial elements:  24
root cutout:      0.04 m
material density: 520 kg/m^3
infill fraction:  0.05
wall thickness:   0.0008 m
hardware mass:    0 g
optimizer:        NLopt LN_COBYLA
max evaluations:  500
relative x tol:   0.001
omega penalty limit: 2500 rad/s
radius bounds:    0.12 0.45 m
"""


class OptimizerResultTests(unittest.TestCase):
    def test_parses_complete_result_and_units(self) -> None:
        result = parse_result(SAMPLE_OUTPUT)

        self.assertEqual(result["status_name"], "XTOL_REACHED")
        self.assertEqual(result["airfoil"], "NACA2409")
        self.assertEqual(result["blade_count"], 3)
        self.assertAlmostEqual(result["objective"], -8.15429)
        self.assertAlmostEqual(result["radius_upper_bound_m"], 0.45)
        self.assertAlmostEqual(
            result["max_rpm"], 31.8834 * 60.0 / (2.0 * math.pi)
        )

    def test_unknown_status_is_preserved(self) -> None:
        result = parse_result(SAMPLE_OUTPUT.replace(
            "Optimization status: 4", "Optimization status: -1"
        ))
        self.assertEqual(result["status_name"], "NLOPT_-1")

    def test_missing_field_has_actionable_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing 'objective'"):
            parse_result(SAMPLE_OUTPUT.replace("objective:", "score:"))

    def test_non_numeric_field_has_actionable_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "'fall time' is not numeric"):
            number("fall time: unavailable\n", "fall time")

    def test_field_names_are_matched_exactly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing 'mass'"):
            field("total mass: 10 g\n", "mass")

    def test_versioned_json_normalizes_units(self) -> None:
        document = {
            "schema_version": 1,
            "status": 4,
            "objective": -8.0,
            "airfoil": "NACA2409",
            "geometry": {
                "radius_m": 0.45, "root_chord_m": 0.08,
                "tip_chord_m": 0.04, "root_pitch_rad": -0.1,
                "tip_twist_rad": 0.15, "blade_count": 3,
                "radial_elements": 24, "root_cutout_m": 0.04,
            },
            "simulation": {
                "fall_time_s": 10.0, "impact_speed_m_s": 2.0,
                "max_omega_rad_s": 30.0, "rotor_mass_kg": 0.06,
                "total_mass_kg": 0.16, "mean_prandtl_factor": 0.9,
                "mean_axial_induction": 0.5,
                "induction_failure_fraction": 0.01,
            },
            "simulation_config": {
                "body_mass_kg": 0.1, "hardware_mass_kg": 0.0,
                "material_density_kg_m3": 520.0, "infill_fraction": 0.05,
                "wall_thickness_m": 0.0008, "release_height_m": 20.0,
                "time_step_s": 0.01,
            },
            "optimization_config": {
                "optimizer": "NLopt LN_COBYLA", "maximum_evaluations": 500,
                "relative_x_tolerance": 0.001,
                "radius_lower_bound_m": 0.12, "radius_upper_bound_m": 0.45,
                "omega_penalty_threshold_rad_s": 2500.0,
            },
        }
        result = parse_result_json(document)
        self.assertAlmostEqual(result["rotor_mass_g"], 60.0)
        self.assertAlmostEqual(result["induction_failure_percent"], 1.0)

    def test_json_schema_version_is_required(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "schema version"):
            parse_result_json({"schema_version": 2})


if __name__ == "__main__":
    unittest.main()
