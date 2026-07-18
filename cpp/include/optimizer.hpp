#pragma once

#include "rotor_model.hpp"
#include "types.hpp"

#include <string>
#include <vector>

struct OptimizationOutcome {
    int status{};
    int evaluations{};
    double objective{};
    RotorGeometry geometry{};
    SimulationResult simulation{};
};

RotorGeometry decode_geometry(const std::vector<double>& values,
                              const std::string& airfoil);
double score_simulation(const SimulationResult& result,
                        const ObjectiveConfig& config = {});
OptimizationOutcome optimize_rotor(RotorModel& model, const std::string& airfoil,
                                   const OptimizationConfig& config = {},
                                   bool verbose = true);
