#pragma once

#include "optimizer.hpp"
#include "types.hpp"

#include <filesystem>
#include <string>
#include <vector>

void write_trace_csv(const std::filesystem::path& path,
                     const std::vector<SimulationSample>& trace);
void write_result_json(const std::filesystem::path& path,
                       const OptimizationOutcome& outcome,
                       const SimulationConfig& simulation_config,
                       const OptimizationConfig& optimization_config,
                       const std::string& backend);
