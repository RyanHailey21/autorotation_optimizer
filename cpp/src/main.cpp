#include "aero_client.hpp"
#include "rotor_model.hpp"
#include "types.hpp"

#include <nlopt.hpp>

#include <exception>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

struct OptimizationContext {
    RotorModel* model;
    std::string airfoil;
    bool verbose{true};
    int evaluations{};
};

static RotorGeometry decode(const std::vector<double>& x, const std::string& airfoil) {
    RotorGeometry g;
    g.radius = x.at(0);
    g.root_chord = x.at(1);
    g.tip_chord = x.at(2);
    g.root_pitch_rad = x.at(3);
    g.tip_twist_rad = x.at(4);
    g.airfoil = airfoil;
    return g;
}

static double objective(const std::vector<double>& x,
                        std::vector<double>&,
                        void* data) {
    auto& ctx = *static_cast<OptimizationContext*>(data);
    const RotorGeometry geometry = decode(x, ctx.airfoil);
    const SimulationResult r = ctx.model->simulate(geometry);
    ++ctx.evaluations;

    if (!r.valid || !r.completed) {
        return 1.0e6;
    }

    const double rpm_penalty = r.max_omega > 2500.0 ? (r.max_omega - 2500.0) * 1e-3 : 0.0;
    const double confidence_penalty = 20.0 * r.extrapolation_fraction;
    const double induction_penalty = 50.0 * r.induction_failure_fraction;
    const double objective_value = -r.fall_time + rpm_penalty + confidence_penalty +
                                   induction_penalty;

    if (ctx.verbose) {
        std::cout << "eval=" << std::setw(4) << ctx.evaluations
                  << " time=" << std::setw(8) << r.fall_time
                  << " impact=" << std::setw(8) << r.impact_speed
                  << " mass=" << std::setw(8) << r.total_mass
                  << " F=" << std::setw(7) << r.mean_prandtl_loss_factor
                  << " a=" << std::setw(7) << r.mean_axial_induction
                  << " fail=" << std::setw(7) << r.induction_failure_fraction
                  << " omega_max=" << std::setw(9) << r.max_omega
                  << " J=" << objective_value << '\n';
    }

    return objective_value;
}

int main(int argc, char** argv) {
    try {
        std::filesystem::path root = ".";
        std::filesystem::path polar_path;
        bool verbose = true;
        for (int i = 1; i < argc; ++i) {
            const std::string argument = argv[i];
            if (argument == "--root" && i + 1 < argc) {
                root = argv[++i];
            } else if (argument == "--polar" && i + 1 < argc) {
                polar_path = argv[++i];
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

        RotorModel model(env, cfg, aero);
        OptimizationContext context{&model, aero.airfoil(), verbose};

        nlopt::opt opt(nlopt::LN_COBYLA, 5);
        opt.set_lower_bounds({0.12, 0.015, 0.010, -0.60, -0.60});
        opt.set_upper_bounds({0.45, 0.100, 0.080,  0.25,  0.60});
        opt.set_min_objective(objective, &context);
        opt.set_maxeval(500);
        opt.set_xtol_rel(1e-3);

        std::vector<double> x{0.25, 0.055, 0.025, -0.12, -0.15};
        double minimum{};
        const nlopt::result status = opt.optimize(x, minimum);

        const RotorGeometry best = decode(x, aero.airfoil());
        const SimulationResult result = model.simulate(best);

        std::cout << "\nOptimization status: " << status << "\n"
                  << "airfoil:         " << best.airfoil << "\n"
                  << "objective:       " << minimum << "\n"
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
                  << " %\n";

        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << '\n';
        return 1;
    }
}
