#!/usr/bin/env python3
"""Local browser application for the autorotation optimization workflow."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from run_optimization import DEFAULT_AIRFOILS, SolverConfiguration, solver_arguments


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "app"
REPORT_ROOT = ROOT / "reports" / "latest"
RUNNER = ROOT / "run.sh"
MAX_REQUEST_BYTES = 64 * 1024
MAX_LOG_LINES = 4000
AIRFOIL_PATTERN = re.compile(r"NACA\d{4}")


class ConfigurationError(ValueError):
    """Raised when a submitted application configuration is invalid."""


@dataclass(frozen=True)
class RunConfiguration:
    backend: str = "neuralfoil"
    airfoils: tuple[str, ...] = tuple(DEFAULT_AIRFOILS)
    jobs: int = min(4, os.cpu_count() or 1)
    force: bool = False
    refresh_polar: bool = False
    solver: SolverConfiguration = SolverConfiguration()


def _finite_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be numeric")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum:g} and {maximum:g}")
    return result


def validate_configuration(value: Any) -> RunConfiguration:
    if not isinstance(value, dict):
        raise ConfigurationError("Configuration must be a JSON object")
    backend = value.get("backend", "neuralfoil")
    if backend not in {"neuralfoil", "fallback"}:
        raise ConfigurationError("Backend must be 'neuralfoil' or 'fallback'")

    raw_airfoils = value.get("airfoils", DEFAULT_AIRFOILS)
    if not isinstance(raw_airfoils, list) or not raw_airfoils:
        raise ConfigurationError("Select at least one airfoil")
    if len(raw_airfoils) > 64:
        raise ConfigurationError("At most 64 airfoils may be selected")
    airfoils: list[str] = []
    for raw_name in raw_airfoils:
        if not isinstance(raw_name, str):
            raise ConfigurationError("Every airfoil must be a string")
        name = raw_name.strip().upper()
        if not AIRFOIL_PATTERN.fullmatch(name):
            raise ConfigurationError(
                f"Invalid airfoil '{raw_name}'; expected a four-digit NACA name"
            )
        if name not in airfoils:
            airfoils.append(name)

    jobs = value.get("jobs", min(4, os.cpu_count() or 1))
    if isinstance(jobs, bool) or not isinstance(jobs, int) or not 1 <= jobs <= 64:
        raise ConfigurationError("Concurrent jobs must be an integer from 1 to 64")

    force = value.get("force", False)
    refresh_polar = value.get("refresh_polar", False)
    if not isinstance(force, bool) or not isinstance(refresh_polar, bool):
        raise ConfigurationError("Cache controls must be true or false")
    raw_solver = value.get("solver", {})
    if not isinstance(raw_solver, dict):
        raise ConfigurationError("Solver configuration must be an object")
    body_mass = _finite_number(raw_solver.get("body_mass_kg", 0.100),
                               "Body mass", 0.001, 10.0)
    release_height = _finite_number(raw_solver.get("release_height_m", 20.0),
                                    "Release height", 0.1, 1000.0)
    maximum_evaluations = raw_solver.get("maximum_evaluations", 500)
    if (isinstance(maximum_evaluations, bool) or
            not isinstance(maximum_evaluations, int) or
            not 1 <= maximum_evaluations <= 100000):
        raise ConfigurationError("Maximum evaluations must be an integer from 1 to 100000")
    tolerance = _finite_number(raw_solver.get("relative_x_tolerance", 1.0e-3),
                               "Relative design tolerance", 1.0e-8, 0.1)
    radius_min = _finite_number(raw_solver.get("radius_min_m", 0.12),
                                "Minimum radius", 0.02, 5.0)
    radius_max = _finite_number(raw_solver.get("radius_max_m", 0.45),
                                "Maximum radius", 0.02, 5.0)
    if radius_min >= radius_max:
        raise ConfigurationError("Minimum radius must be smaller than maximum radius")
    omega_threshold = _finite_number(
        raw_solver.get("omega_penalty_threshold_rad_s", 2500.0),
        "Rotor-speed penalty threshold", 1.0, 100000.0,
    )
    return RunConfiguration(
        backend=backend,
        airfoils=tuple(airfoils),
        jobs=jobs,
        force=force,
        refresh_polar=refresh_polar,
        solver=SolverConfiguration(
            body_mass_kg=body_mass,
            release_height_m=release_height,
            maximum_evaluations=maximum_evaluations,
            relative_x_tolerance=tolerance,
            radius_min_m=radius_min,
            radius_max_m=radius_max,
            omega_penalty_threshold_rad_s=omega_threshold,
        ),
    )


def command_for(configuration: RunConfiguration) -> list[str]:
    command = [
        "bash", str(RUNNER),
        "--backend", configuration.backend,
        "--jobs", str(configuration.jobs),
    ]
    if configuration.force:
        command.append("--force")
    if configuration.refresh_polar:
        command.append("--refresh-polar")
    command.extend(["--airfoils", *configuration.airfoils])
    command.extend(solver_arguments(configuration.solver))
    return command


@dataclass
class RunState:
    id: str
    configuration: RunConfiguration
    status: str = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    message: str = "Waiting to start"
    log: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    process: subprocess.Popen[str] | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "configuration": asdict(self.configuration),
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "message": self.message,
            "log": list(self.log),
        }
        result["configuration"]["airfoils"] = list(self.configuration.airfoils)
        return result


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: RunState | None = None

    def current(self) -> dict[str, Any] | None:
        with self._lock:
            return None if self._current is None else self._current.public()

    def start(self, configuration: RunConfiguration) -> dict[str, Any]:
        with self._lock:
            if self._current and self._current.status in {"queued", "running", "cancelling"}:
                raise ConfigurationError("An optimization is already running")
            state = RunState(id=uuid.uuid4().hex, configuration=configuration)
            self._current = state
            threading.Thread(target=self._execute, args=(state,), daemon=True).start()
            return state.public()

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            state = self._current
            if state is None or state.status not in {"queued", "running"}:
                raise ConfigurationError("There is no active optimization to cancel")
            state.status = "cancelling"
            state.message = "Cancellation requested"
            process = state.process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return state.public()

    def _execute(self, state: RunState) -> None:
        try:
            with self._lock:
                if state.status == "cancelling":
                    state.status = "cancelled"
                    state.finished_at = time.time()
                    return
                state.status = "running"
                state.started_at = time.time()
                state.message = "Optimization workflow is running"

            process = subprocess.Popen(
                command_for(state.configuration),
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                start_new_session=True,
            )
            with self._lock:
                state.process = process
                cancellation_pending = state.status == "cancelling"
            if cancellation_pending and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            assert process.stdout is not None
            for line in process.stdout:
                with self._lock:
                    state.log.append(line.rstrip())
            exit_code = process.wait()
            with self._lock:
                state.exit_code = exit_code
                state.finished_at = time.time()
                state.process = None
                if state.status == "cancelling":
                    state.status = "cancelled"
                    state.message = "Optimization cancelled"
                elif exit_code == 0:
                    state.status = "completed"
                    state.message = "Optimization completed successfully"
                else:
                    state.status = "failed"
                    state.message = f"Optimization exited with code {exit_code}"
        except Exception as error:  # Keep the server alive and expose the failure.
            with self._lock:
                state.status = "failed"
                state.message = str(error)
                state.finished_at = time.time()
                state.process = None


class ApplicationHandler(BaseHTTPRequestHandler):
    manager: RunManager

    def log_message(self, format: str, *args: object) -> None:
        print(f"[app] {self.address_string()} {format % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/config":
            self._json({
                "defaults": self._configuration_json(RunConfiguration()),
                "airfoils": DEFAULT_AIRFOILS,
                "maximum_jobs": 64,
            })
        elif path == "/api/runs/current":
            self._json({"run": self.manager.current()})
        elif path == "/api/results":
            summary_path = REPORT_ROOT / "summary.json"
            if not summary_path.exists():
                self._json({"available": False})
            else:
                try:
                    summary = json.loads(summary_path.read_text())
                except (OSError, json.JSONDecodeError) as error:
                    self._error(500, f"Unable to read report summary: {error}")
                    return
                self._json({"available": True, "summary": summary})
        elif path == "/report" or path == "/report/":
            self._redirect("/report/report.html")
        elif path.startswith("/report/"):
            self._serve_report(path.removeprefix("/report/"))
        else:
            self._serve_application(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            self._require_same_origin()
            if path == "/api/runs":
                state = self.manager.start(validate_configuration(self._request_json()))
                self._json({"run": state}, status=202)
            elif path == "/api/runs/current/cancel":
                self._json({"run": self.manager.cancel()})
            else:
                self._error(404, "Unknown endpoint")
        except ConfigurationError as error:
            self._error(409 if "already running" in str(error) else 400, str(error))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._error(400, "Request body must be valid UTF-8 JSON")

    def _require_same_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            raise ConfigurationError("Cross-origin requests are not allowed")

    @staticmethod
    def _configuration_json(configuration: RunConfiguration) -> dict[str, Any]:
        result = asdict(configuration)
        result["airfoils"] = list(configuration.airfoils)
        return result

    def _request_json(self) -> Any:
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ConfigurationError("A valid Content-Length header is required") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ConfigurationError("Request body is too large")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _serve_application(self, path: str) -> None:
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        }
        item = files.get(path)
        if item is None:
            self._error(404, "Not found")
            return
        self._file(WEB_ROOT / item[0], item[1], no_store=True)

    def _serve_report(self, relative: str) -> None:
        files = {
            "report.html": "text/html; charset=utf-8",
            "plotly.min.js": "text/javascript; charset=utf-8",
            "summary.json": "application/json; charset=utf-8",
            "leaderboard.csv": "text/csv; charset=utf-8",
            "best-trace.csv": "text/csv; charset=utf-8",
        }
        content_type = files.get(relative)
        if content_type is None:
            self._error(404, "Report artifact not found")
            return
        self._file(REPORT_ROOT / relative, content_type, no_store=True)

    def _file(self, path: Path, content_type: str, *, no_store: bool) -> None:
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            self._error(404, "File not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store" if no_store else "public, max-age=300")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, value: Any, *, status: int = 200) -> None:
        content = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status=status)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()


def serve(host: str, port: int, *, open_browser: bool) -> None:
    manager = RunManager()
    handler = type("BoundApplicationHandler", (ApplicationHandler,), {"manager": manager})
    server = ThreadingHTTPServer((host, port), handler)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/"
    print(f"Autorotation Optimizer application: {url}")
    print("Press Ctrl+C to stop the application server.")
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping application server.")
    finally:
        try:
            manager.cancel()
        except ConfigurationError:
            pass
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    serve("127.0.0.1", args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    main()
