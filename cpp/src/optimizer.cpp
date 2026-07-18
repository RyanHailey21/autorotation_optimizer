#include "optimizer.hpp"

#include <nlopt.hpp>

#include <iomanip>
#include <iostream>
#include <stdexcept>

namespace {
struct OptimizationContext {
    RotorModel* model;
    std::string airfoil;
    ObjectiveConfig objective_config;
    bool verbose;
    int evaluations{};
};

double objective_callback(const std::vector<double>& values,
                          std::vector<double>&,
                          void* data) {
    auto& context = *static_cast<OptimizationContext*>(data);
    const SimulationResult result = context.model->simulate(
        decode_geometry(values, context.airfoil));
    ++context.evaluations;
    const double objective = score_simulation(result, context.objective_config);

    if (context.verbose) {
        std::cout << "eval=" << std::setw(4) << context.evaluations
                  << " time=" << std::setw(8) << result.fall_time
                  << " impact=" << std::setw(8) << result.impact_speed
                  << " mass=" << std::setw(8) << result.total_mass
                  << " F=" << std::setw(7) << result.mean_prandtl_loss_factor
                  << " a=" << std::setw(7) << result.mean_axial_induction
                  << " fail=" << std::setw(7) << result.induction_failure_fraction
                  << " omega_max=" << std::setw(9) << result.max_omega
                  << " J=" << objective << '\n';
    }
    return objective;
}
} // namespace

RotorGeometry decode_geometry(const std::vector<double>& values,
                              const std::string& airfoil) {
    if (values.size() != OptimizationConfig::variable_count) {
        throw std::invalid_argument("Rotor design vector must contain five values");
    }
    RotorGeometry geometry;
    geometry.radius = values[0];
    geometry.root_chord = values[1];
    geometry.tip_chord = values[2];
    geometry.root_pitch_rad = values[3];
    geometry.tip_twist_rad = values[4];
    geometry.airfoil = airfoil;
    return geometry;
}

double score_simulation(const SimulationResult& result,
                        const ObjectiveConfig& config) {
    if (!result.valid || !result.completed) {
        return config.invalid_result_penalty;
    }
    const double omega_penalty = result.max_omega > config.maximum_omega
        ? (result.max_omega - config.maximum_omega) * config.omega_penalty_scale
        : 0.0;
    return -result.fall_time + omega_penalty +
        config.extrapolation_penalty_scale * result.extrapolation_fraction +
        config.induction_failure_penalty_scale * result.induction_failure_fraction;
}

OptimizationOutcome optimize_rotor(RotorModel& model, const std::string& airfoil,
                                   const OptimizationConfig& config, bool verbose) {
    OptimizationContext context{
        &model, airfoil, config.objective, verbose
    };
    nlopt::opt optimizer(nlopt::LN_COBYLA, OptimizationConfig::variable_count);
    optimizer.set_lower_bounds(std::vector<double>(
        config.lower_bounds.begin(), config.lower_bounds.end()));
    optimizer.set_upper_bounds(std::vector<double>(
        config.upper_bounds.begin(), config.upper_bounds.end()));
    optimizer.set_min_objective(objective_callback, &context);
    optimizer.set_maxeval(config.maximum_evaluations);
    optimizer.set_xtol_rel(config.relative_x_tolerance);

    std::vector<double> values(config.initial_values.begin(), config.initial_values.end());
    double objective{};
    const nlopt::result status = optimizer.optimize(values, objective);
    const RotorGeometry geometry = decode_geometry(values, airfoil);
    return {
        .status = static_cast<int>(status),
        .evaluations = context.evaluations,
        .objective = objective,
        .geometry = geometry,
        .simulation = model.simulate(geometry),
    };
}
