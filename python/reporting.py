"""Generate self-contained engineering reports from cached optimizer outputs."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import re
import shutil


STATUS_NAMES = {
    1: "SUCCESS",
    2: "STOPVAL_REACHED",
    3: "FTOL_REACHED",
    4: "XTOL_REACHED",
    5: "MAXEVAL_REACHED",
    6: "MAXTIME_REACHED",
}


def field(output: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", output, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Optimizer output is missing '{name}'")
    return match.group(1).strip()


def number(output: str, name: str) -> float:
    return float(field(output, name).split()[0])


def parse_result(output: str) -> dict[str, float | int | str]:
    status = int(field(output, "Optimization status"))
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
        "max_omega_rad_s": number(output, "max omega"),
        "max_rpm": number(output, "max omega") * 60.0 / (2.0 * math.pi),
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
        "radius_lower_bound_m": float(field(output, "radius bounds").split()[0]),
        "radius_upper_bound_m": float(field(output, "radius bounds").split()[1]),
    }


def read_trace(path: Path) -> list[dict[str, float]]:
    with path.open(newline="") as stream:
        return [
            {key: float(value) for key, value in row.items()}
            for row in csv.DictReader(stream)
        ]


def downsample(rows: list[dict[str, float]], maximum: int = 420) -> list[dict[str, float]]:
    if len(rows) <= maximum:
        return rows
    step = (len(rows) - 1) / (maximum - 1)
    return [rows[round(i * step)] for i in range(maximum)]


def line_chart(rows: list[dict[str, float]], key: str, title: str, unit: str,
               series_class: str, include_zero: bool = False) -> str:
    rows = downsample(rows)
    width, height = 760, 205
    left, right, top, bottom = 58, 18, 25, 38
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = [row["time_s"] for row in rows]
    ys = [row[key] for row in rows]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if include_zero:
        y0 = min(0.0, y0)
        y1 = max(0.0, y1)
    padding = max((y1 - y0) * 0.08, 1.0e-9)
    y0 -= padding
    y1 += padding

    def sx(value: float) -> float:
        return left + (value - x0) / max(x1 - x0, 1.0e-9) * plot_w

    def sy(value: float) -> float:
        return top + (y1 - value) / max(y1 - y0, 1.0e-9) * plot_h

    points = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in zip(xs, ys))
    grid = []
    labels = []
    for index in range(5):
        fraction = index / 4
        x = left + fraction * plot_w
        value = x0 + fraction * (x1 - x0)
        grid.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}"/>')
        labels.append(f'<text x="{x:.1f}" y="{height - 12}" text-anchor="middle">{value:.1f}</text>')
    for index in range(4):
        fraction = index / 3
        y = top + fraction * plot_h
        value = y1 - fraction * (y1 - y0)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}"/>')
        labels.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{value:.3g}</text>')
    return f'''<figure class="plot">
<figcaption>{html.escape(title)}</figcaption>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)} over time">
  <g class="grid">{''.join(grid)}</g>
  <g class="axis-labels">{''.join(labels)}
    <text x="{left + plot_w / 2:.1f}" y="{height - 1}" text-anchor="middle">Time (s)</text>
    <text x="12" y="{top + plot_h / 2:.1f}" text-anchor="middle" transform="rotate(-90 12 {top + plot_h / 2:.1f})">{html.escape(unit)}</text>
  </g>
  <polyline class="series {series_class}" points="{points}"/>
</svg></figure>'''


def leaderboard_chart(results: list[dict[str, object]]) -> str:
    width = 760
    row_height = 25
    height = 32 + row_height * len(results)
    left, right = 92, 68
    maximum = max(float(result["metrics"]["fall_time_s"]) for result in results)
    bars = []
    for index, result in enumerate(results):
        metrics = result["metrics"]
        value = float(metrics["fall_time_s"])
        y = 22 + index * row_height
        bar_width = (width - left - right) * value / maximum
        selected = " selected" if index == 0 else ""
        bars.append(
            f'<text x="{left - 8}" y="{y + 13}" text-anchor="end">{metrics["airfoil"]}</text>'
            f'<rect class="bar{selected}" x="{left}" y="{y}" width="{bar_width:.1f}" height="16" rx="2"/>'
            f'<text x="{left + bar_width + 7:.1f}" y="{y + 13}">{value:.2f} s</text>'
        )
    return f'''<figure class="leaderboard">
<figcaption>Optimized airfoil comparison</figcaption>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="Fall time for each optimized NACA airfoil">{''.join(bars)}</svg>
</figure>'''


def rotor_diagram(metrics: dict[str, float | int | str]) -> str:
    radius = float(metrics["radius_m"])
    root = float(metrics["root_chord_m"])
    tip = float(metrics["tip_chord_m"])
    scale = 245 / radius
    hub = 0.04 * scale
    blade_radius = radius * scale
    root_half = root * scale / 2
    tip_half = tip * scale / 2
    polygon = f"{hub:.1f},{-root_half:.1f} {blade_radius:.1f},{-tip_half:.1f} {blade_radius:.1f},{tip_half:.1f} {hub:.1f},{root_half:.1f}"
    blades = "".join(
        f'<polygon points="{polygon}" transform="rotate({angle})"/>'
        for angle in (0, 120, 240)
    )
    return f'''<figure class="rotor">
<figcaption>Optimized three-blade planform</figcaption>
<svg viewBox="0 0 620 560" role="img" aria-label="Three-bladed rotor planform for {metrics['airfoil']}">
  <g transform="translate(310 280)" class="blades">{blades}<circle r="{hub:.1f}"/></g>
  <g class="dimension"><line x1="310" y1="535" x2="{310 + blade_radius:.1f}" y2="535"/><text x="{310 + blade_radius / 2:.1f}" y="525" text-anchor="middle">R = {radius * 1000:.1f} mm</text></g>
</svg></figure>'''


def generate_report(results: list[dict[str, object]], report_dir: Path,
                    backend: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        result["metrics"] = parse_result(str(result["output"]))
    results.sort(key=lambda item: float(item["metrics"]["objective"]))
    best = results[0]
    metrics = best["metrics"]
    trace = read_trace(Path(best["trace_path"]))
    shutil.copyfile(Path(best["trace_path"]), report_dir / "best-trace.csv")

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = {
        "generated_utc": generated,
        "backend": backend,
        "best": metrics,
        "leaderboard": [result["metrics"] for result in results],
        "trace_file": "best-trace.csv",
    }
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (report_dir / "leaderboard.csv").open("w", newline="") as stream:
        columns = ["airfoil", "objective", "fall_time_s", "impact_speed_m_s",
                   "total_mass_g", "status_name", "induction_failure_percent"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for result in results:
            writer.writerow({key: result["metrics"][key] for key in columns})

    constraint = "Radius upper bound active" if float(metrics["radius_m"]) >= float(metrics["radius_upper_bound_m"]) - 1.0e-4 else "No radius bound active"
    plots = "".join([
        line_chart(trace, "height_m", "Altitude history", "Height (m)", "s1", True),
        line_chart(trace, "down_speed_m_s", "Descent velocity", "Speed (m/s)", "s2", True),
        line_chart(trace, "omega_rad_s", "Rotor angular velocity", "Omega (rad/s)", "s3", True),
        line_chart(trace, "mean_axial_induction", "Axial induction", "Induction factor a", "s4", True),
        line_chart(trace, "axial_force_n", "Rotor axial force", "Force (N)", "s5", True),
        line_chart(trace, "aero_torque_nm", "Aerodynamic torque", "Torque (N m)", "s6", True),
    ])
    report = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Autorotation Optimization Report - {metrics['airfoil']}</title>
<style>
:root{{--bg:#f5f7fa;--panel:#fff;--text:#17202a;--muted:#5d6976;--border:#d9e0e7;--grid:#dfe5eb;--s1:#1261a0;--s2:#9a4d00;--s3:#6b4c9a;--s4:#087f5b;--s5:#b02a37;--s6:#51606f;--accent:#0b6e4f}}
@media(prefers-color-scheme:dark){{:root{{--bg:#101419;--panel:#171d23;--text:#e7edf3;--muted:#aab5c0;--border:#35404a;--grid:#2d3740;--accent:#5bc8a3}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:28px}}h1{{font-size:25px;margin:0 0 4px}}h2{{font-size:18px;margin:32px 0 12px}}.subtitle{{color:var(--muted);margin:0 0 22px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}.card{{background:var(--panel);border:1px solid var(--border);border-radius:7px;padding:14px}}.label{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}}.value{{font-size:22px;margin-top:3px}}.two{{display:grid;grid-template-columns:minmax(300px,1fr) minmax(300px,1fr);gap:18px;align-items:start}}figure{{margin:0}}figcaption{{font-weight:600;margin:0 0 8px}}svg{{width:100%;height:auto;background:var(--panel);border:1px solid var(--border);border-radius:7px}}.grid line{{stroke:var(--grid);stroke-width:1}}.axis-labels{{fill:var(--muted);font-size:11px}}.series{{fill:none;stroke-width:2}}.s1{{stroke:var(--s1)}}.s2{{stroke:var(--s2)}}.s3{{stroke:var(--s3)}}.s4{{stroke:var(--s4)}}.s5{{stroke:var(--s5)}}.s6{{stroke:var(--s6)}}.bar{{fill:var(--grid)}}.bar.selected{{fill:var(--accent)}}.leaderboard text{{fill:var(--text);font-size:12px}}.blades polygon{{fill:color-mix(in srgb,var(--accent) 24%,transparent);stroke:var(--accent);stroke-width:1.5}}.blades circle{{fill:var(--panel);stroke:var(--accent);stroke-width:2}}.dimension line{{stroke:var(--muted)}}.dimension text{{fill:var(--text);font-size:13px}}.plots{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}table{{width:100%;border-collapse:collapse;background:var(--panel)}}th,td{{padding:8px 10px;border-bottom:1px solid var(--border);text-align:left}}th{{color:var(--muted);font-weight:500}}code{{font-family:ui-monospace,monospace}}footer{{color:var(--muted);margin-top:28px;font-size:12px}}@media(max-width:760px){{main{{padding:16px}}.two,.plots{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Autorotation Optimization Report</h1><p class="subtitle">Engineering optimization | {html.escape(str(backend))} aerodynamics | generated {generated}</p>
<section class="cards">
<div class="card"><div class="label">Best airfoil</div><div class="value">{metrics['airfoil']}</div></div>
<div class="card"><div class="label">Fall time</div><div class="value">{metrics['fall_time_s']:.2f} s</div></div>
<div class="card"><div class="label">Impact speed</div><div class="value">{metrics['impact_speed_m_s']:.3f} m/s</div></div>
<div class="card"><div class="label">Total mass</div><div class="value">{metrics['total_mass_g']:.1f} g</div></div>
<div class="card"><div class="label">Peak rotor speed</div><div class="value">{metrics['max_rpm']:.0f} RPM</div></div>
<div class="card"><div class="label">NLopt status</div><div class="value">{metrics['status_name']}</div></div>
</section>
<h2>Design and search result</h2><div class="two">{rotor_diagram(metrics)}{leaderboard_chart(results)}</div>
<h2>Best-design transient</h2><div class="plots">{plots}</div>
<h2>Engineering record</h2><div class="two"><table><tbody>
<tr><th>Radius</th><td>{metrics['radius_m'] * 1000:.2f} mm</td></tr><tr><th>Root chord</th><td>{metrics['root_chord_m'] * 1000:.2f} mm</td></tr><tr><th>Tip chord</th><td>{metrics['tip_chord_m'] * 1000:.2f} mm</td></tr><tr><th>Root pitch</th><td>{metrics['root_pitch_rad']:.6f} rad</td></tr><tr><th>Tip twist</th><td>{metrics['tip_twist_rad']:.6f} rad</td></tr><tr><th>Rotor mass</th><td>{metrics['rotor_mass_g']:.3f} g</td></tr><tr><th>Constraint state</th><td>{constraint}</td></tr>
</tbody></table><table><tbody>
<tr><th>Objective</th><td>{metrics['objective']:.6f}</td></tr><tr><th>Mean axial induction</th><td>{metrics['mean_axial_induction']:.6f}</td></tr><tr><th>Mean Prandtl factor</th><td>{metrics['mean_prandtl_factor']:.6f}</td></tr><tr><th>Induction failures</th><td>{metrics['induction_failure_percent']:.3f}%</td></tr><tr><th>Discretization</th><td>{metrics['time_step_s']:.4f} s, {metrics['radial_elements']} annuli</td></tr><tr><th>Optimizer</th><td>{metrics['optimizer']}, {metrics['maximum_evaluations']} max evals, x-tol {metrics['relative_x_tolerance']:.1e}</td></tr><tr><th>Print model</th><td>ASA Aero, {metrics['material_density_kg_m3']:.0f} kg/m^3, {metrics['infill_fraction'] * 100:.0f}% infill, {metrics['wall_thickness_m'] * 1000:.1f} mm walls</td></tr><tr><th>Artifacts</th><td><code>summary.json</code>, <code>leaderboard.csv</code>, <code>best-trace.csv</code></td></tr>
</tbody></table></div>
<footer>Quasi-steady axial BEMT with NeuralFoil interpolation, Buhl high-induction correction, and Prandtl tip/root losses. Review current model limitations before design release.</footer>
</main></body></html>'''
    report_path = report_dir / "report.html"
    report_path.write_text(report)
    return report_path
