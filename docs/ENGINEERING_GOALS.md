# Engineering goals and model basis

## Mission

Optimize a passive, three-bladed autorotation device that carries a fixed
100 g drone body and electronics package. The primary simulated performance
goal is a long, controlled descent from a 20 m release while tracking impact
speed, rotor speed, mass, aerodynamic validity, and nonlinear-solver health.

The optimizer is a design-screening and analysis tool. Its results are not a
release authorization without independent model correlation, structural
assessment, and physical drop testing.

## Current full optimization case

The design problem has one discrete and five continuous decisions:

1. NACA four-digit airfoil identity;
2. rotor radius;
3. root chord;
4. tip chord;
5. root pitch; and
6. tip twist.

The outer airfoil set contains 16 sections: NACA 0009/0012/0015/0018,
2409/2412/2415/2418, 4409/4412/4415/4418, and
6409/6412/6415/6418. Each airfoil receives an independent continuous NLopt
COBYLA search rather than sharing geometry with another section.

Current continuous bounds are:

| Variable | Lower | Upper |
| --- | ---: | ---: |
| Radius | 0.12 m | 0.45 m |
| Root chord | 0.015 m | 0.100 m |
| Tip chord | 0.010 m | 0.080 m |
| Root pitch | -0.60 rad | 0.25 rad |
| Tip twist | -0.60 rad | 0.60 rad |

The production search currently allows 500 evaluations per airfoil with a
relative design tolerance of 1e-3. These are part of the problem definition,
not incidental implementation details.

## Physical model

The transient simulation integrates vertical translation and rotor speed. Its
quasi-steady, axial BEMT annulus solve uses cached NeuralFoil section tables,
previous-step induction warm starts, bounded bracketing and bisection, Buhl
high-induction behavior, and Prandtl tip and root/hub corrections.

The simulation currently uses:

- three rotor blades;
- 24 radial elements and a 0.04 m root cutout;
- 1.225 kg/m^3 air density and 9.80665 m/s^2 gravity;
- a 20 m release from rest;
- 5 rad/s initial rotor speed;
- a 0.01 s integration step;
- blade polar inertia recomputed for each candidate; and
- explicit constant and viscous bearing-torque terms.

NeuralFoil must remain outside the optimization loop. It generates cached polar
tables before optimization; the C++ solver performs only in-memory
interpolation during objective evaluations. NeuralFoil 0.3.x is incompressible,
so the current low-subsonic Mach dimension repeats its coefficients. That is a
documented limitation, not validated compressibility modeling.

## Mass and manufacturing basis

Total simulated mass is:

`100 g body/electronics + three printed blades + supplied hardware mass`

The printed blades currently assume Bambu ASA Aero with:

- 520 kg/m^3 effective deposited-material density;
- 5% interior infill;
- two 0.4 mm walls; and
- NACA-thickness-dependent cross-sectional area.

The effective density must be replaced or calibrated with coupons or blade
measurements made using the actual printer, temperature, wall count, infill,
and drying process. Hub, fastener, support, and deployment hardware mass and
inertia are currently zero placeholders pending measurements or CAD properties.

## Objective and diagnostics

The current scalar objective minimizes negative fall time, with additive
penalties for:

- maximum angular speed above 2500 rad/s;
- aerodynamic-table extrapolation; and
- failed axial-induction solves.

Impact speed, total and rotor mass, maximum angular speed, mean Prandtl factor,
mean axial induction, and induction-failure fraction are mandatory reported
outputs even when they are not separate constraints. Optimization status and
penalties must stay auditable.

The engineering report must show all six design variables for every airfoil,
not just the winning geometry. It must also retain the full candidate
leaderboard, final transient histories, solver diagnostics, active problem
configuration, CSV/JSON data, and a final-design trace. Report generation is
post-processing and must not add telemetry or plotting work to objective calls.

## Current regression reference

The cached full-case run at the time this document was written selected
NACA2409 with the following values:

| Quantity | Value |
| --- | ---: |
| Objective | -8.15429 |
| Radius | 0.45 m |
| Root chord | 0.0799726 m |
| Tip chord | 0.0386206 m |
| Root pitch | -0.10691 rad |
| Tip twist | 0.157847 rad |
| Simulated fall time | 9.94 s |
| Simulated impact speed | 1.86975 m/s |
| Rotor mass | 66.0147 g |
| Total mass | 166.015 g |
| Maximum angular speed | 31.8834 rad/s |
| Mean Prandtl factor | 0.93049 |
| Mean axial induction | 0.50362 |
| Induction failure fraction | 0% |

Use this only as a regression reference. It is neither a frozen expected answer
nor evidence that the design is physically validated. Intentional changes to
the model, design space, objective, polar data, or optimizer may legitimately
change it; explain and quantify those changes.

## Validation boundaries and next goals

Prioritize model credibility before expanding the search space:

1. Verify blade-element force, torque, angle, and sign conventions against
   hand calculations at selected states.
2. Compare fixed-geometry, fixed-RPM loads with an independent BEMT
   implementation and document tolerances.
3. Validate the axial-induction solution across normal and high-induction
   regimes; then assess and implement tangential wake induction if justified.
4. Replace extrapolated or incomplete section behavior with validated
   360-degree/dynamic-stall data appropriate to autorotation.
5. Measure ASA Aero blade mass and polar inertia and correlate the manufacturing
   model.
6. Add measured or CAD-derived hub, fastener, bearing, support, and deployment
   mass/inertia.
7. Add body drag, structural stress/deflection, manufacturability, clearance,
   and deployment constraints.
8. Correlate predicted rotor speed, descent velocity, and impact speed with
   instrumented drop tests over multiple geometries.
9. Perform mesh, time-step, polar-grid, optimizer-start, and tolerance
   sensitivity studies before treating rankings as robust.
10. Quantify uncertainty in mass, aerodynamic coefficients, bearing friction,
    atmosphere, and fabrication, then report performance margins rather than a
    single deterministic optimum.

Any result intended for hardware selection should state the code revision,
polar provenance, complete configuration, cache key, solver status, and known
validation gaps.
