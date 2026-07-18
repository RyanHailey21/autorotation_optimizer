"""Generate offline Plotly engineering reports from cached optimizer outputs."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import shutil

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
import plotly.io as pio
from plotly.subplots import make_subplots

from optimizer_result import parse_result


PLOT_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": True,
    "toImageButtonOptions": {"format": "svg", "filename": "autorotation-plot"},
}
DESIGN_COLUMNS = [
    "airfoil", "radius_m", "root_chord_m", "tip_chord_m",
    "root_pitch_rad", "tip_twist_rad",
]
REPORT_COLUMNS = DESIGN_COLUMNS + [
    "objective", "fall_time_s", "impact_speed_m_s", "rotor_mass_g",
    "total_mass_g", "max_rpm", "status_name", "mean_prandtl_factor",
    "mean_axial_induction", "induction_failure_percent",
]


def read_trace(path: Path) -> list[dict[str, float]]:
    with path.open(newline="") as stream:
        return [
            {key: float(value) for key, value in row.items()}
            for row in csv.DictReader(stream)
        ]


def downsample(rows: list[dict[str, float]], maximum: int = 500) -> list[dict[str, float]]:
    if len(rows) <= maximum:
        return rows
    step = (len(rows) - 1) / (maximum - 1)
    return [rows[round(index * step)] for index in range(maximum)]


def plot_html(figure: go.Figure, div_id: str) -> str:
    return pio.to_html(
        figure, include_plotlyjs=False, full_html=False, config=PLOT_CONFIG,
        div_id=div_id, validate=True,
    )


def common_layout(figure: go.Figure, title: str, height: int) -> None:
    figure.update_layout(
        template="plotly_white",
        title={"text": title, "x": 0.02, "xanchor": "left"},
        height=height,
        margin={"l": 60, "r": 28, "t": 58, "b": 48},
        font={"family": "system-ui, sans-serif", "size": 12},
        hoverlabel={"font_size": 12},
    )


def leaderboard_figure(results: list[dict[str, object]]) -> go.Figure:
    metrics = [result["metrics"] for result in reversed(results)]
    custom = [
        [item["impact_speed_m_s"], item["total_mass_g"], item["objective"]]
        for item in metrics
    ]
    colors = ["#0b6e4f" if item["airfoil"] == results[0]["metrics"]["airfoil"] else "#aeb8c2" for item in metrics]
    figure = go.Figure(go.Bar(
        x=[item["fall_time_s"] for item in metrics],
        y=[item["airfoil"] for item in metrics],
        orientation="h",
        marker_color=colors,
        text=[f"{item['fall_time_s']:.2f} s" for item in metrics],
        textposition="outside",
        customdata=custom,
        hovertemplate=(
            "%{y}<br>Fall time: %{x:.3f} s<br>Impact: %{customdata[0]:.3f} m/s"
            "<br>Total mass: %{customdata[1]:.2f} g<br>Objective: %{customdata[2]:.4f}<extra></extra>"
        ),
    ))
    common_layout(figure, "Optimized airfoil comparison", 485)
    figure.update_xaxes(title="Fall time (s)", rangemode="tozero")
    figure.update_yaxes(title=None)
    return figure


def design_space_figure(results: list[dict[str, object]]) -> go.Figure:
    metrics = [result["metrics"] for result in results]
    dimensions = [
        {"label": "Airfoil", "values": list(range(len(metrics))),
         "tickvals": list(range(len(metrics))), "ticktext": [item["airfoil"] for item in metrics]},
        {"label": "Radius (mm)", "values": [item["radius_m"] * 1000 for item in metrics]},
        {"label": "Root chord (mm)", "values": [item["root_chord_m"] * 1000 for item in metrics]},
        {"label": "Tip chord (mm)", "values": [item["tip_chord_m"] * 1000 for item in metrics]},
        {"label": "Root pitch (deg)", "values": [math.degrees(item["root_pitch_rad"]) for item in metrics]},
        {"label": "Tip twist (deg)", "values": [math.degrees(item["tip_twist_rad"]) for item in metrics]},
    ]
    figure = go.Figure(go.Parcoords(
        line={
            "color": [item["fall_time_s"] for item in metrics],
            "colorscale": "Viridis",
            "showscale": True,
            "colorbar": {"title": "Fall time (s)"},
        },
        dimensions=dimensions,
        labelfont={"size": 12},
        tickfont={"size": 10},
    ))
    common_layout(figure, "All optimized design variables", 430)
    figure.update_layout(margin={"l": 70, "r": 90, "t": 85, "b": 40})
    return figure


def rotor_figure(metrics: dict[str, float | int | str]) -> go.Figure:
    radius = float(metrics["radius_m"])
    root_radius = float(metrics["root_cutout_m"])
    root_half = float(metrics["root_chord_m"]) / 2.0
    tip_half = float(metrics["tip_chord_m"]) / 2.0
    figure = go.Figure()
    for angle_degrees in (0.0, 120.0, 240.0):
        angle = math.radians(angle_degrees)
        local = [
            (root_radius, -root_half), (radius, -tip_half),
            (radius, tip_half), (root_radius, root_half), (root_radius, -root_half),
        ]
        x = [axial * math.cos(angle) - lateral * math.sin(angle) for axial, lateral in local]
        y = [axial * math.sin(angle) + lateral * math.cos(angle) for axial, lateral in local]
        figure.add_trace(go.Scatter(
            x=x, y=y, mode="lines", fill="toself", fillcolor="rgba(11,110,79,0.22)",
            line={"color": "#0b6e4f", "width": 2}, hoverinfo="skip", showlegend=False,
        ))
    figure.add_shape(type="circle", x0=-root_radius, x1=root_radius,
                     y0=-root_radius, y1=root_radius, line_color="#0b6e4f")
    common_layout(figure, f"Optimized three-blade planform — {metrics['airfoil']}", 485)
    figure.update_xaxes(title="x (m)", scaleanchor="y", scaleratio=1, zeroline=False)
    figure.update_yaxes(title="y (m)", zeroline=False)
    return figure


def transient_figure(rows: list[dict[str, float]]) -> go.Figure:
    rows = downsample(rows)
    time = [row["time_s"] for row in rows]
    definitions = [
        ("height_m", "Altitude", "m", "#1261a0"),
        ("down_speed_m_s", "Descent speed", "m/s", "#9a4d00"),
        ("omega_rad_s", "Rotor speed", "rad/s", "#6b4c9a"),
        ("mean_axial_induction", "Axial induction", "a", "#087f5b"),
        ("axial_force_n", "Axial force", "N", "#b02a37"),
        ("aero_torque_nm", "Aerodynamic torque", "N m", "#51606f"),
    ]
    figure = make_subplots(rows=3, cols=2, subplot_titles=[item[1] for item in definitions],
                           horizontal_spacing=0.10, vertical_spacing=0.12)
    for index, (key, title, unit, color) in enumerate(definitions):
        row, column = index // 2 + 1, index % 2 + 1
        figure.add_trace(go.Scatter(
            x=time, y=[sample[key] for sample in rows], mode="lines",
            line={"color": color, "width": 2}, name=title,
            hovertemplate=f"Time: %{{x:.3f}} s<br>{title}: %{{y:.5g}} {unit}<extra></extra>",
            showlegend=False,
        ), row=row, col=column)
        figure.update_xaxes(title="Time (s)" if row == 3 else None, row=row, col=column)
        figure.update_yaxes(title=unit, row=row, col=column)
    common_layout(figure, "Best-design transient histories", 820)
    figure.update_layout(hovermode="x unified")
    return figure


def design_table(results: list[dict[str, object]]) -> str:
    rows = []
    for result in results:
        metrics = result["metrics"]
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(metrics['airfoil']))}</td>"
            f"<td>{metrics['radius_m'] * 1000:.2f}</td>"
            f"<td>{metrics['root_chord_m'] * 1000:.2f}</td>"
            f"<td>{metrics['tip_chord_m'] * 1000:.2f}</td>"
            f"<td>{math.degrees(metrics['root_pitch_rad']):.3f}</td>"
            f"<td>{math.degrees(metrics['tip_twist_rad']):.3f}</td>"
            f"<td>{metrics['objective']:.5f}</td>"
            f"<td>{metrics['fall_time_s']:.3f}</td>"
            "</tr>"
        )
    return (
        "<div class=table-wrap><table><thead><tr><th>Airfoil</th><th>Radius (mm)</th>"
        "<th>Root chord (mm)</th><th>Tip chord (mm)</th><th>Root pitch (deg)</th>"
        "<th>Tip twist (deg)</th><th>Objective</th><th>Fall time (s)</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def generate_report(results: list[dict[str, object]], report_dir: Path,
                    backend: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        if "metrics" not in result:
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
        "design_variables": DESIGN_COLUMNS,
        "best": metrics,
        "leaderboard": [result["metrics"] for result in results],
        "trace_file": "best-trace.csv",
    }
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (report_dir / "leaderboard.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow({key: result["metrics"][key] for key in REPORT_COLUMNS})

    (report_dir / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    constraint = (
        "Radius upper bound active"
        if float(metrics["radius_m"]) >= float(metrics["radius_upper_bound_m"]) - 1.0e-4
        else "No radius bound active"
    )
    rotor_plot = plot_html(rotor_figure(metrics), "rotor-planform")
    leaderboard_plot = plot_html(leaderboard_figure(results), "airfoil-leaderboard")
    design_plot = plot_html(design_space_figure(results), "design-space")
    transient_plot = plot_html(transient_figure(trace), "transient-history")
    report = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Autorotation Optimization Report - {metrics['airfoil']}</title><script src="plotly.min.js"></script>
<style>
:root{{--bg:#f5f7fa;--panel:#fff;--text:#17202a;--muted:#5d6976;--border:#d9e0e7}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}}main{{max-width:1240px;margin:auto;padding:28px}}h1{{font-size:25px;margin:0 0 4px}}h2{{font-size:18px;margin:32px 0 12px}}.subtitle{{color:var(--muted);margin:0 0 22px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}}.card,.plot{{background:var(--panel);border:1px solid var(--border);border-radius:7px}}.card{{padding:14px}}.plot{{overflow:hidden}}.label{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}}.value{{font-size:22px;margin-top:3px}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}}table{{width:100%;border-collapse:collapse;background:var(--panel)}}th,td{{padding:8px 10px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-weight:500}}.table-wrap{{border:1px solid var(--border);border-radius:7px;overflow-x:auto}}code{{font-family:ui-monospace,monospace}}footer{{color:var(--muted);margin-top:28px;font-size:12px}}@media(max-width:820px){{main{{padding:16px}}.two{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Autorotation Optimization Report</h1><p class="subtitle">Engineering optimization | {html.escape(str(backend))} aerodynamics | generated {generated}</p>
<section class="cards"><div class="card"><div class="label">Best airfoil</div><div class="value">{metrics['airfoil']}</div></div><div class="card"><div class="label">Fall time</div><div class="value">{metrics['fall_time_s']:.2f} s</div></div><div class="card"><div class="label">Impact speed</div><div class="value">{metrics['impact_speed_m_s']:.3f} m/s</div></div><div class="card"><div class="label">Total mass</div><div class="value">{metrics['total_mass_g']:.1f} g</div></div><div class="card"><div class="label">Peak rotor speed</div><div class="value">{metrics['max_rpm']:.0f} RPM</div></div><div class="card"><div class="label">NLopt status</div><div class="value">{metrics['status_name']}</div></div></section>
<h2>Design and search result</h2><div class="two"><div class="plot">{rotor_plot}</div><div class="plot">{leaderboard_plot}</div></div>
<h2>All optimized design variables</h2><div class="plot">{design_plot}</div>{design_table(results)}
<h2>Best-design transient</h2><div class="plot">{transient_plot}</div>
<h2>Engineering record</h2><div class="two"><table><tbody><tr><th>Airfoil</th><td>{metrics['airfoil']}</td></tr><tr><th>Radius</th><td>{metrics['radius_m'] * 1000:.2f} mm</td></tr><tr><th>Root chord</th><td>{metrics['root_chord_m'] * 1000:.2f} mm</td></tr><tr><th>Tip chord</th><td>{metrics['tip_chord_m'] * 1000:.2f} mm</td></tr><tr><th>Root pitch</th><td>{metrics['root_pitch_rad']:.6f} rad</td></tr><tr><th>Tip twist</th><td>{metrics['tip_twist_rad']:.6f} rad</td></tr><tr><th>Rotor mass</th><td>{metrics['rotor_mass_g']:.3f} g</td></tr><tr><th>Constraint state</th><td>{constraint}</td></tr></tbody></table><table><tbody><tr><th>Objective</th><td>{metrics['objective']:.6f}</td></tr><tr><th>Mean axial induction</th><td>{metrics['mean_axial_induction']:.6f}</td></tr><tr><th>Mean Prandtl factor</th><td>{metrics['mean_prandtl_factor']:.6f}</td></tr><tr><th>Induction failures</th><td>{metrics['induction_failure_percent']:.3f}%</td></tr><tr><th>Discretization</th><td>{metrics['time_step_s']:.4f} s, {metrics['radial_elements']} annuli</td></tr><tr><th>Optimizer</th><td>{metrics['optimizer']}, {metrics['maximum_evaluations']} max evals, x-tol {metrics['relative_x_tolerance']:.1e}</td></tr><tr><th>Rotor-speed penalty</th><td>above {metrics['omega_penalty_threshold_rad_s']:.1f} rad/s</td></tr><tr><th>Print model</th><td>ASA Aero, {metrics['material_density_kg_m3']:.0f} kg/m^3, {metrics['infill_fraction'] * 100:.0f}% infill, {metrics['wall_thickness_m'] * 1000:.1f} mm walls</td></tr><tr><th>Artifacts</th><td><code>summary.json</code>, <code>leaderboard.csv</code>, <code>best-trace.csv</code></td></tr></tbody></table></div>
<footer>Quasi-steady axial BEMT with NeuralFoil interpolation, Buhl high-induction correction, and Prandtl tip/root losses. Review engineering validation boundaries before design release.</footer>
</main></body></html>'''
    report_path = report_dir / "report.html"
    report_path.write_text(report, encoding="utf-8")
    return report_path
