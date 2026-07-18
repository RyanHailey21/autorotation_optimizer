#include "rotor_model.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <vector>

RotorModel::RotorModel(Environment env, SimulationConfig cfg, AeroClient aero)
    : env_(env), cfg_(cfg), aero_(std::move(aero)) {}

double RotorModel::lerp(double a, double b, double t) {
    return a + (b - a) * t;
}

double RotorModel::airfoil_area_coefficient(const std::string& airfoil) {
    // Integral of the closed NACA four-digit thickness distribution, normalized
    // by chord squared: area/c^2 = 0.685083 * (thickness/chord).
    if (airfoil.size() == 8 && airfoil.rfind("NACA", 0) == 0 &&
        std::isdigit(static_cast<unsigned char>(airfoil[6])) &&
        std::isdigit(static_cast<unsigned char>(airfoil[7]))) {
        const double thickness_fraction =
            (10.0 * (airfoil[6] - '0') + (airfoil[7] - '0')) / 100.0;
        return 0.685083 * thickness_fraction;
    }
    throw std::invalid_argument(
        "Printed-mass model requires a four-digit NACA airfoil name: " + airfoil);
}

RotorModel::RotorMassProperties RotorModel::rotor_mass_properties(
    const RotorGeometry& g) const {
    // Integrate printed cross-section along each blade. The perimeter term models
    // solid walls; only the remaining interior receives the requested infill.
    constexpr int mass_elements = 400;
    const double dr = (g.radius - g.root_cutout) / mass_elements;
    const double area_coefficient = airfoil_area_coefficient(g.airfoil);
    double blade_mass = 0.0;
    double blade_inertia = 0.0;
    for (int i = 0; i < mass_elements; ++i) {
        const double r = g.root_cutout + (i + 0.5) * dr;
        const double eta = (r - g.root_cutout) / (g.radius - g.root_cutout);
        const double chord = lerp(g.root_chord, g.tip_chord, eta);
        const double solid_area = area_coefficient * chord * chord;
        const double wall_area = std::min(
            solid_area, cfg_.airfoil_perimeter_coefficient * chord * cfg_.wall_thickness);
        const double printed_area = wall_area +
            cfg_.infill_fraction * (solid_area - wall_area);
        const double dm = cfg_.print_material_density * printed_area * dr;
        blade_mass += dm;
        blade_inertia += dm * r * r;
    }
    return {
        g.blade_count * blade_mass + cfg_.printed_hardware_mass,
        g.blade_count * blade_inertia + cfg_.printed_hardware_inertia
    };
}

SimulationResult RotorModel::simulate(const RotorGeometry& g) const {
    return simulate_impl<false>(g, nullptr);
}

SimulationResult RotorModel::simulate_with_trace(
    const RotorGeometry& g, std::vector<SimulationSample>& trace) const {
    trace.clear();
    return simulate_impl<true>(g, &trace);
}

template<bool RecordTrace>
SimulationResult RotorModel::simulate_impl(
    const RotorGeometry& g, std::vector<SimulationSample>* trace) const {
    if (g.radius <= g.root_cutout || g.root_chord <= 0.0 || g.tip_chord <= 0.0 ||
        g.blade_count < 1 || g.radial_elements < 4) {
        return {.completed = false, .valid = false};
    }

    if (cfg_.body_mass <= 0.0 || cfg_.print_material_density <= 0.0 ||
        cfg_.infill_fraction < 0.0 || cfg_.infill_fraction > 1.0 ||
        cfg_.wall_thickness < 0.0) {
        return {.completed = false, .valid = false};
    }
    const auto mass_properties = rotor_mass_properties(g);
    const double rotor_mass = mass_properties.mass;
    const double total_mass = cfg_.body_mass + rotor_mass;
    const double inertia = mass_properties.inertia;
    if (inertia <= 0.0) {
        return {.completed = false, .valid = false};
    }

    double height = cfg_.release_height;
    double down_speed = cfg_.initial_down_speed;
    double omega = cfg_.initial_omega;
    double time = 0.0;
    double max_omega = omega;
    std::size_t low_confidence_count = 0;
    std::size_t aero_count = 0;
    double prandtl_factor_sum = 0.0;
    std::size_t induction_solve_count = 0;
    std::size_t induction_failure_count = 0;
    double axial_induction_sum = 0.0;

    const double dr = (g.radius - g.root_cutout) / g.radial_elements;
    std::vector<double> induction_warm_start(g.radial_elements, 0.0);

    while (height > 0.0 && time < cfg_.max_time) {
        double step_prandtl_sum = 0.0;
        double step_induction_sum = 0.0;
        std::size_t step_induction_count = 0;
        std::size_t step_induction_failures = 0;
        struct ElementState {
            double r;
            double chord;
            double vrel;
            double phi;
            double induction;
            double prandtl_loss;
            double residual;
            AeroCoefficients coefficients;
        };
        std::vector<ElementState> elements;
        elements.reserve(g.radial_elements);

        for (int i = 0; i < g.radial_elements; ++i) {
            const double r = g.root_cutout + (i + 0.5) * dr;
            const double eta = (r - g.root_cutout) / (g.radius - g.root_cutout);
            const double chord = lerp(g.root_chord, g.tip_chord, eta);
            const double pitch = g.root_pitch_rad + g.tip_twist_rad * eta;
            const double tangential = std::max(std::abs(omega * r), 1e-3);

            const auto evaluate_induction = [&](double induction) {
                const double axial = std::max(down_speed * (1.0 - induction), 1e-3);
                const double phi = std::atan2(axial, tangential);
                const double alpha = pitch + phi;
                const double vrel = std::hypot(tangential, axial);
                const double reynolds = env_.density * vrel * chord /
                                        env_.dynamic_viscosity;
                const double mach = vrel / 343.0;
                const auto coefficients = aero_.evaluate({
                    g.airfoil, alpha * 180.0 / std::numbers::pi, reynolds, mach
                });
                const double sin_phi = std::max(std::abs(std::sin(phi)), 1.0e-6);
                const double tip_exponent = -0.5 * g.blade_count *
                    (g.radius - r) / (r * sin_phi);
                const double root_exponent = -0.5 * g.blade_count *
                    (r - g.root_cutout) / (r * sin_phi);
                const double tip_loss = (2.0 / std::numbers::pi) *
                    std::acos(std::clamp(std::exp(tip_exponent), 0.0, 1.0));
                const double root_loss = (2.0 / std::numbers::pi) *
                    std::acos(std::clamp(std::exp(root_exponent), 0.0, 1.0));
                const double loss = std::clamp(tip_loss * root_loss, 1.0e-3, 1.0);
                const double q = 0.5 * env_.density * vrel * vrel;
                const double dL = q * chord * coefficients.cl * dr * g.blade_count;
                const double dD = q * chord * coefficients.cd * dr * g.blade_count;
                const double dAxial = dL * std::cos(phi) + dD * std::sin(phi);
                const double annulus_dynamic_force = std::max(
                    std::numbers::pi * env_.density * r * dr * down_speed * down_speed,
                    1.0e-9);
                const double blade_ct = dAxial / annulus_dynamic_force;
                double momentum_ct;
                if (induction <= 0.4) {
                    momentum_ct = 4.0 * loss * induction * (1.0 - induction);
                } else {
                    // Buhl's continuous high-induction extension of Glauert's
                    // correction, including the local Prandtl factor.
                    momentum_ct = 8.0 / 9.0 + (4.0 * loss - 40.0 / 9.0) * induction +
                        (50.0 / 9.0 - 4.0 * loss) * induction * induction;
                }
                return ElementState{
                    r, chord, vrel, phi, induction, loss,
                    blade_ct - momentum_ct, coefficients
                };
            };

            ElementState solution = evaluate_induction(0.0);
            bool converged = true;
            if (down_speed >= 0.25) {
                constexpr double minimum_induction = -0.5;
                constexpr double maximum_induction = 0.95;
                const double warm = std::clamp(
                    induction_warm_start[i], minimum_induction, maximum_induction);
                solution = evaluate_induction(warm);
                double best_residual = std::abs(solution.residual);
                bool have_bracket = false;
                double bracket_lower = minimum_induction;
                double bracket_upper = maximum_induction;
                double half_width = 0.02;

                // Warm starts normally bracket the next timestep's root in only
                // a few coefficient lookups. Expand geometrically if needed.
                for (int attempt = 0; attempt < 8 && !have_bracket; ++attempt) {
                    bracket_lower = std::max(minimum_induction, warm - half_width);
                    bracket_upper = std::min(maximum_induction, warm + half_width);
                    ElementState lower = evaluate_induction(bracket_lower);
                    ElementState upper = evaluate_induction(bracket_upper);
                    for (const auto& candidate : {lower, upper}) {
                        if (std::abs(candidate.residual) < best_residual) {
                            solution = candidate;
                            best_residual = std::abs(candidate.residual);
                        }
                    }
                    have_bracket = std::isfinite(lower.residual) &&
                        std::isfinite(upper.residual) && lower.residual * upper.residual <= 0.0;
                    half_width *= 2.0;
                }

                if (have_bracket) {
                    ElementState lower = evaluate_induction(bracket_lower);
                    for (int iteration = 0; iteration < 24; ++iteration) {
                        const double midpoint = 0.5 * (bracket_lower + bracket_upper);
                        ElementState middle = evaluate_induction(midpoint);
                        solution = middle;
                        if (std::abs(middle.residual) < 1.0e-5) {
                            break;
                        }
                        if (lower.residual * middle.residual <= 0.0) {
                            bracket_upper = midpoint;
                        } else {
                            bracket_lower = midpoint;
                            lower = middle;
                        }
                    }
                }
                converged = have_bracket && std::abs(solution.residual) < 1.0e-3;
                ++induction_solve_count;
                ++step_induction_count;
                axial_induction_sum += solution.induction;
                step_induction_sum += solution.induction;
                if (!converged) {
                    ++induction_failure_count;
                    ++step_induction_failures;
                }
            }
            induction_warm_start[i] = solution.induction;
            elements.push_back(solution);
        }

        double axial_force = 0.0; // upward positive
        double aero_torque = 0.0; // positive increases omega

        for (const auto& element : elements) {
            const auto& c = element.coefficients;
            const double q = 0.5 * env_.density * element.vrel * element.vrel;
            const double dL = q * element.chord * c.cl * dr * g.blade_count;
            const double dD = q * element.chord * c.cd * dr * g.blade_count;

            // Resolve section forces from relative wind coordinates.
            const double dAxial = dL * std::cos(element.phi) + dD * std::sin(element.phi);
            const double dTangential = dL * std::sin(element.phi) - dD * std::cos(element.phi);

            axial_force += dAxial;
            aero_torque += dTangential * element.r;

            ++aero_count;
            prandtl_factor_sum += element.prandtl_loss;
            step_prandtl_sum += element.prandtl_loss;
            if (c.confidence < 0.5) {
                ++low_confidence_count;
            }
        }

        const double bearing_torque = cfg_.bearing_torque_constant +
                                      cfg_.bearing_torque_viscous * std::abs(omega);
        const double domega = (aero_torque - std::copysign(bearing_torque, omega)) / inertia;
        const double acceleration_down = env_.gravity - axial_force / total_mass;

        omega += domega * cfg_.dt;
        omega = std::max(omega, 0.0);
        down_speed += acceleration_down * cfg_.dt;
        down_speed = std::max(down_speed, 0.0);
        height -= down_speed * cfg_.dt;
        time += cfg_.dt;
        max_omega = std::max(max_omega, omega);

        if constexpr (RecordTrace) {
            trace->push_back({
                .time = time,
                .height = std::max(height, 0.0),
                .down_speed = down_speed,
                .omega = omega,
                .axial_force = axial_force,
                .aero_torque = aero_torque,
                .mean_prandtl_loss_factor = step_prandtl_sum /
                    static_cast<double>(g.radial_elements),
                .mean_axial_induction = step_induction_count == 0 ? 0.0 :
                    step_induction_sum / static_cast<double>(step_induction_count),
                .induction_failure_fraction = step_induction_count == 0 ? 0.0 :
                    static_cast<double>(step_induction_failures) /
                    static_cast<double>(step_induction_count)
            });
        }

        if (!std::isfinite(height) || !std::isfinite(down_speed) || !std::isfinite(omega) ||
            omega > cfg_.max_omega) {
            return {.completed = false, .valid = false, .fall_time = time,
                    .impact_speed = down_speed, .max_omega = max_omega,
                    .rotor_mass = rotor_mass, .total_mass = total_mass,
                    .mean_prandtl_loss_factor = aero_count == 0 ? 1.0 :
                        prandtl_factor_sum / static_cast<double>(aero_count),
                    .mean_axial_induction = induction_solve_count == 0 ? 0.0 :
                        axial_induction_sum / static_cast<double>(induction_solve_count),
                    .induction_failure_fraction = induction_solve_count == 0 ? 0.0 :
                        static_cast<double>(induction_failure_count) /
                        static_cast<double>(induction_solve_count)};
        }
    }

    return {
        .completed = height <= 0.0,
        .valid = true,
        .fall_time = time,
        .impact_speed = down_speed,
        .max_omega = max_omega,
        .extrapolation_fraction = aero_count == 0 ? 1.0 :
            static_cast<double>(low_confidence_count) / static_cast<double>(aero_count),
        .rotor_mass = rotor_mass,
        .total_mass = total_mass,
        .mean_prandtl_loss_factor = aero_count == 0 ? 1.0 :
            prandtl_factor_sum / static_cast<double>(aero_count),
        .mean_axial_induction = induction_solve_count == 0 ? 0.0 :
            axial_induction_sum / static_cast<double>(induction_solve_count),
        .induction_failure_fraction = induction_solve_count == 0 ? 0.0 :
            static_cast<double>(induction_failure_count) /
            static_cast<double>(induction_solve_count)
    };
}
