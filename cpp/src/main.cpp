#include "aero_client.hpp"
#include "optimizer.hpp"
#include "result_io.hpp"
#include "rotor_model.hpp"
#include "types.hpp"

#include <exception>
#include <filesystem>
#include <iostream>
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
        for (int i = 1; i < argc; ++i) {
            const std::string argument = argv[i];
            if (argument == "--root" && i + 1 < argc) {
                root = argv[++i];
            } else if (argument == "--polar" && i + 1 < argc) {
                polar_path = argv[++i];
            } else if (argument == "--trace" && i + 1 < argc) {
                trace_path = argv[++i];
            } else if (argument == "--result-json" && i + 1 < argc) {
                result_json_path = argv[++i];
            } else if (argument == "--quiet") {
                verbose = false;
            } else {
                throw std::invalid_argument("Unknown or incomplete argument: " + argument);
            }
        }
        if (polar_path.empty()) {
            polar_path = root / "data/aero_polar.csv";
        }
        AeroClient aero(polar_path);
        std::cout << "Loaded " << aero.backend() << " polar for "
                  << aero.airfoil() << " (optimization uses table interpolation)\n";

        Environment env;
        SimulationConfig cfg;
        OptimizationConfig optimization_config;

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
                  << "radius bounds:    " << optimization_config.lower_bounds[0] << " "
                  << optimization_config.upper_bounds[0]
                  << " m\n";

        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << '\n';
        return 1;
    }
}
