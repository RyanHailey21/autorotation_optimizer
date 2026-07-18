#include "aero_client.hpp"
#include "optimizer.hpp"
#include "result_io.hpp"
#include "rotor_model.hpp"
#include "types.hpp"

#include <exception>
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    try {
        std::filesystem::path root = ".";
        std::filesystem::path polar_path;
        std::filesystem::path trace_path;
        std::filesystem::path result_json_path;
        bool verbose = true;
        SimulationConfig cfg;
        OptimizationConfig optimization_config;
        const auto parse_double = [](const std::string& text, const std::string& option) {
            std::size_t consumed{};
            const double value = std::stod(text, &consumed);
            if (consumed != text.size() || !std::isfinite(value)) {
                throw std::invalid_argument("Invalid numeric value for " + option + ": " + text);
            }
            return value;
        };
        const auto parse_integer = [](const std::string& text, const std::string& option) {
            std::size_t consumed{};
            const long value = std::stol(text, &consumed);
            if (consumed != text.size() || value > std::numeric_limits<int>::max()) {
                throw std::invalid_argument("Invalid integer value for " + option + ": " + text);
            }
            return static_cast<int>(value);
        };
        for (int i = 1; i < argc; ++i) {
            const std::string argument = argv[i];
            const auto next = [&]() -> std::string {
                if (i + 1 >= argc) {
                    throw std::invalid_argument("Missing value for argument: " + argument);
                }
                return argv[++i];
            };
            if (argument == "--root") {
                root = next();
            } else if (argument == "--polar") {
                polar_path = next();
            } else if (argument == "--trace") {
                trace_path = next();
            } else if (argument == "--result-json") {
                result_json_path = next();
            } else if (argument == "--body-mass-kg") {
                cfg.body_mass = parse_double(next(), argument);
            } else if (argument == "--release-height-m") {
                cfg.release_height = parse_double(next(), argument);
            } else if (argument == "--max-evaluations") {
                optimization_config.maximum_evaluations = parse_integer(next(), argument);
            } else if (argument == "--relative-x-tolerance") {
                optimization_config.relative_x_tolerance = parse_double(next(), argument);
            } else if (argument == "--radius-min-m") {
                optimization_config.lower_bounds[0] = parse_double(next(), argument);
            } else if (argument == "--radius-max-m") {
                optimization_config.upper_bounds[0] = parse_double(next(), argument);
            } else if (argument == "--omega-penalty-threshold-rad-s") {
                optimization_config.objective.maximum_omega = parse_double(next(), argument);
            } else if (argument == "--quiet") {
                verbose = false;
            } else {
                throw std::invalid_argument("Unknown or incomplete argument: " + argument);
            }
        }
        if (polar_path.empty()) {
            polar_path = root / "data/aero_polar.csv";
        }
        if (cfg.body_mass <= 0.0 || cfg.release_height <= 0.0 ||
            optimization_config.maximum_evaluations < 1 ||
            optimization_config.relative_x_tolerance <= 0.0 ||
            optimization_config.lower_bounds[0] <= 0.0 ||
            optimization_config.lower_bounds[0] >= optimization_config.upper_bounds[0] ||
            optimization_config.objective.maximum_omega <= 0.0) {
            throw std::invalid_argument("Invalid simulation or optimization configuration");
        }
        optimization_config.initial_values[0] = std::clamp(
            optimization_config.initial_values[0],
            optimization_config.lower_bounds[0],
            optimization_config.upper_bounds[0]);
        AeroClient aero(polar_path);
        std::cout << "Loaded " << aero.backend() << " polar for "
                  << aero.airfoil() << " (optimization uses table interpolation)\n";

        Environment env;
        RotorModel model(env, cfg, aero);
        OptimizationOutcome outcome = optimize_rotor(
            model, aero.airfoil(), optimization_config, verbose);
        const RotorGeometry& best = outcome.geometry;
        std::vector<SimulationSample> trace;
        if (!trace_path.empty()) {
            outcome.simulation = model.simulate_with_trace(best, trace);
        }
        const SimulationResult& result = outcome.simulation;
        if (!trace_path.empty()) {
            write_trace_csv(trace_path, trace);
        }
        if (!result_json_path.empty()) {
            write_result_json(result_json_path, outcome, cfg, optimization_config,
                              aero.backend());
        }

        std::cout << "\nOptimization status: " << outcome.status << "\n"
                  << "airfoil:         " << best.airfoil << "\n"
                  << "objective:       " << outcome.objective << "\n"
                  << "radius:          " << best.radius << " m\n"
                  << "root chord:      " << best.root_chord << " m\n"
                  << "tip chord:       " << best.tip_chord << " m\n"
                  << "root pitch:      " << best.root_pitch_rad << " rad\n"
                  << "tip twist:       " << best.tip_twist_rad << " rad\n"
                  << "blade count:     " << best.blade_count << "\n"
                  << "rotor mass:      " << result.rotor_mass * 1000.0 << " g\n"
                  << "body mass:       " << cfg.body_mass * 1000.0 << " g\n"
                  << "total mass:      " << result.total_mass * 1000.0 << " g\n"
                  << "fall time:       " << result.fall_time << " s\n"
                  << "impact speed:    " << result.impact_speed << " m/s\n"
                  << "max omega:       " << result.max_omega << " rad/s\n";
        std::cout << "mean tip/root F: " << result.mean_prandtl_loss_factor << "\n";
        std::cout << "mean induction a:" << result.mean_axial_induction << "\n"
                  << "induction failed: " << result.induction_failure_fraction * 100.0
                  << " %\n"
                  << "release height:   " << cfg.release_height << " m\n"
                  << "time step:        " << cfg.dt << " s\n"
                  << "radial elements:  " << best.radial_elements << "\n"
                  << "root cutout:      " << best.root_cutout << " m\n"
                  << "material density: " << cfg.print_material_density << " kg/m^3\n"
                  << "infill fraction:  " << cfg.infill_fraction << "\n"
                  << "wall thickness:   " << cfg.wall_thickness << " m\n"
                  << "hardware mass:    " << cfg.printed_hardware_mass * 1000.0 << " g\n"
                  << "optimizer:        NLopt LN_COBYLA\n"
                  << "max evaluations:  " << optimization_config.maximum_evaluations << "\n"
                  << "relative x tol:   " << optimization_config.relative_x_tolerance << "\n"
                  << "omega penalty limit: "
                  << optimization_config.objective.maximum_omega << " rad/s\n"
                  << "radius bounds:    " << optimization_config.lower_bounds[0] << " "
                  << optimization_config.upper_bounds[0]
                  << " m\n";

        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << '\n';
        return 1;
    }
}
