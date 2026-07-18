"""Tests for local application configuration and command construction."""

from __future__ import annotations

import unittest

from application import (
    ConfigurationError,
    RunConfiguration,
    command_for,
    validate_configuration,
)
from run_optimization import SolverConfiguration


class ApplicationConfigurationTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_airfoils(self) -> None:
        configuration = validate_configuration({
            "backend": "fallback",
            "airfoils": ["naca0012", "NACA0012", " NACA2409 "],
            "jobs": 2,
            "force": True,
            "refresh_polar": False,
        })
        self.assertEqual(configuration.airfoils, ("NACA0012", "NACA2409"))
        self.assertEqual(configuration.jobs, 2)
        self.assertTrue(configuration.force)

    def test_rejects_invalid_or_empty_airfoil_sets(self) -> None:
        for value in ([], ["NACA12"], ["CLARKY"], [12]):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                validate_configuration({"airfoils": value})

    def test_rejects_boolean_and_out_of_range_job_counts(self) -> None:
        for value in (True, 0, 65, 1.5, "4"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                validate_configuration({"jobs": value})

    def test_builds_argument_safe_runner_command(self) -> None:
        configuration = RunConfiguration(
            backend="fallback",
            airfoils=("NACA0012", "NACA2409"),
            jobs=2,
            force=True,
            refresh_polar=True,
            solver=SolverConfiguration(body_mass_kg=0.2),
        )
        command = command_for(configuration)
        self.assertEqual(command[0], "bash")
        self.assertIn("--force", command)
        self.assertIn("--refresh-polar", command)
        airfoil_index = command.index("--airfoils")
        self.assertEqual(command[airfoil_index + 1:airfoil_index + 3],
                         ["NACA0012", "NACA2409"])
        self.assertEqual(command[command.index("--body-mass-kg") + 1], "0.2")

    def test_defaults_use_engineering_backend(self) -> None:
        configuration = validate_configuration({})
        self.assertEqual(configuration.backend, "neuralfoil")
        self.assertGreater(len(configuration.airfoils), 0)

    def test_rejects_invalid_engineering_configuration(self) -> None:
        cases = [
            {"body_mass_kg": 0},
            {"release_height_m": -1},
            {"maximum_evaluations": True},
            {"radius_min_m": 0.5, "radius_max_m": 0.4},
            {"relative_x_tolerance": "small"},
        ]
        for solver in cases:
            with self.subTest(solver=solver), self.assertRaises(ConfigurationError):
                validate_configuration({"solver": solver})


if __name__ == "__main__":
    unittest.main()
