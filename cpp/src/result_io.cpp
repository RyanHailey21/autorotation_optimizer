#include "result_io.hpp"

#include <fstream>
#include <iomanip>
#include <stdexcept>

namespace {
std::ofstream open_output(const std::filesystem::path& path, const char* description) {
    if (!path.parent_path().empty()) {
        std::filesystem::create_directories(path.parent_path());
    }
    std::ofstream output(path);
    if (!output) {
        throw std::runtime_error(std::string("Unable to write ") + description + ": " +
                                 path.string());
    }
    return output;
}

void json_string(std::ostream& output, const std::string& value) {
    output << '"';
    for (const char character : value) {
        if (character == '"' || character == '\\') {
            output << '\\';
        }
        output << character;
    }
    output << '"';
}
} // namespace

void write_trace_csv(const std::filesystem::path& path,
                     const std::vector<SimulationSample>& trace) {
    auto output = open_output(path, "simulation trace");
    output << "time_s,height_m,down_speed_m_s,omega_rad_s,axial_force_n,"
              "aero_torque_nm,mean_prandtl_factor,mean_axial_induction,"
              "induction_failure_fraction\n";
    output << std::setprecision(10);
    for (const auto& sample : trace) {
        output << sample.time << ',' << sample.height << ',' << sample.down_speed << ','
               << sample.omega << ',' << sample.axial_force << ',' << sample.aero_torque
               << ',' << sample.mean_prandtl_loss_factor << ','
               << sample.mean_axial_induction << ','
               << sample.induction_failure_fraction << '\n';
    }
}

void write_result_json(const std::filesystem::path& path,
                       const OptimizationOutcome& outcome,
                       const SimulationConfig& simulation_config,
                       const OptimizationConfig& optimization_config,
                       const std::string& backend) {
    auto output = open_output(path, "optimizer JSON result");
    output << std::setprecision(17);
    const auto& geometry = outcome.geometry;
    const auto& result = outcome.simulation;
    output << "{\n  \"schema_version\": 1,\n  \"backend\": ";
    json_string(output, backend);
    output << ",\n  \"status\": " << outcome.status
           << ",\n  \"evaluations\": " << outcome.evaluations
           << ",\n  \"objective\": " << outcome.objective
           << ",\n  \"airfoil\": ";
    json_string(output, geometry.airfoil);
    output << ",\n  \"geometry\": {"
           << "\n    \"radius_m\": " << geometry.radius
           << ",\n    \"root_chord_m\": " << geometry.root_chord
           << ",\n    \"tip_chord_m\": " << geometry.tip_chord
           << ",\n    \"root_pitch_rad\": " << geometry.root_pitch_rad
           << ",\n    \"tip_twist_rad\": " << geometry.tip_twist_rad
           << ",\n    \"blade_count\": " << geometry.blade_count
           << ",\n    \"radial_elements\": " << geometry.radial_elements
           << ",\n    \"root_cutout_m\": " << geometry.root_cutout << "\n  },"
           << "\n  \"simulation\": {"
           << "\n    \"completed\": " << (result.completed ? "true" : "false")
           << ",\n    \"valid\": " << (result.valid ? "true" : "false")
           << ",\n    \"fall_time_s\": " << result.fall_time
           << ",\n    \"impact_speed_m_s\": " << result.impact_speed
           << ",\n    \"max_omega_rad_s\": " << result.max_omega
           << ",\n    \"extrapolation_fraction\": " << result.extrapolation_fraction
           << ",\n    \"rotor_mass_kg\": " << result.rotor_mass
           << ",\n    \"total_mass_kg\": " << result.total_mass
           << ",\n    \"mean_prandtl_factor\": " << result.mean_prandtl_loss_factor
           << ",\n    \"mean_axial_induction\": " << result.mean_axial_induction
           << ",\n    \"induction_failure_fraction\": " << result.induction_failure_fraction
           << "\n  },\n  \"simulation_config\": {"
           << "\n    \"body_mass_kg\": " << simulation_config.body_mass
           << ",\n    \"hardware_mass_kg\": " << simulation_config.printed_hardware_mass
           << ",\n    \"material_density_kg_m3\": " << simulation_config.print_material_density
           << ",\n    \"infill_fraction\": " << simulation_config.infill_fraction
           << ",\n    \"wall_thickness_m\": " << simulation_config.wall_thickness
           << ",\n    \"release_height_m\": " << simulation_config.release_height
           << ",\n    \"time_step_s\": " << simulation_config.dt << "\n  },"
           << "\n  \"optimization_config\": {"
           << "\n    \"optimizer\": \"NLopt LN_COBYLA\""
           << ",\n    \"maximum_evaluations\": " << optimization_config.maximum_evaluations
           << ",\n    \"relative_x_tolerance\": " << optimization_config.relative_x_tolerance
           << ",\n    \"radius_lower_bound_m\": " << optimization_config.lower_bounds[0]
           << ",\n    \"radius_upper_bound_m\": " << optimization_config.upper_bounds[0]
           << "\n  }\n}\n";
}
