"""Cache-key contract tests for optimization orchestration."""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import run_optimization


class CacheKeyTests(unittest.TestCase):
    def test_optimization_key_covers_executable_and_polar_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "optimizer"
            polar = root / "polar.csv"
            executable.write_bytes(b"executable-v1")
            polar.write_bytes(b"polar-v1")
            with patch.object(run_optimization, "EXECUTABLE", executable):
                original = run_optimization.optimization_key(polar)
                polar.write_bytes(b"polar-v2")
                polar_changed = run_optimization.optimization_key(polar)
                polar.write_bytes(b"polar-v1")
                executable.write_bytes(b"executable-v2")
                executable_changed = run_optimization.optimization_key(polar)

            self.assertNotEqual(original, polar_changed)
            self.assertNotEqual(original, executable_changed)

    def test_report_key_covers_metrics_trace_and_generator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generator = root / "reporting.py"
            trace = root / "trace.csv"
            generator.write_bytes(b"generator-v1")
            trace.write_bytes(b"trace-v1")
            results = [{"metrics": {"objective": -8.0}, "trace_path": trace}]
            with patch.object(run_optimization, "REPORT_GENERATOR", generator), \
                    patch.object(run_optimization, "package_version", return_value="1.0"):
                original = run_optimization.report_key(results, "neuralfoil")
                results[0]["metrics"] = {"objective": -9.0}
                metrics_changed = run_optimization.report_key(results, "neuralfoil")
                results[0]["metrics"] = {"objective": -8.0}
                trace.write_bytes(b"trace-v2")
                trace_changed = run_optimization.report_key(results, "neuralfoil")
                trace.write_bytes(b"trace-v1")
                generator.write_bytes(b"generator-v2")
                generator_changed = run_optimization.report_key(results, "neuralfoil")

            self.assertNotEqual(original, metrics_changed)
            self.assertNotEqual(original, trace_changed)
            self.assertNotEqual(original, generator_changed)


if __name__ == "__main__":
    unittest.main()
