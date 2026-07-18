#pragma once

#include <array>
#include <string>

struct AeroQuery {
    std::string airfoil{"NACA2412"};
    double alpha_deg{};
    double reynolds{};
    double mach{};
};

struct AeroCoefficients {
    double cl{};
    double cd{};
    double cm{};
    double confidence{1.0};
};

struct RotorGeometry {
    int blade_count{3};
    int radial_elements{24};
    double radius{0.25};
    double root_cutout{0.04};
    double root_chord{0.055};
    double tip_chord{0.025};
    double root_pitch_rad{-0.12};
    double tip_twist_rad{-0.15};
    std::string airfoil{"NACA2412"};
};

struct Environment {
    double density{1.225};
    double dynamic_viscosity{1.81e-5};
    double gravity{9.80665};
};

struct SimulationConfig {
    double body_mass{0.100};
    double printed_hardware_mass{0.0};
    double printed_hardware_inertia{0.0};
    double print_material_density{520.0};
    double infill_fraction{0.05};
    double wall_thickness{0.0008};
    double airfoil_perimeter_coefficient{2.04};
    double release_height{20.0};
    double initial_down_speed{0.0};
    double initial_omega{5.0};
    double dt{0.01};
    double max_time{120.0};
    double bearing_torque_constant{2.0e-5};
    double bearing_torque_viscous{2.0e-7};
    double max_omega{4000.0};
};

struct SimulationResult {
    bool completed{false};
    bool valid{true};
    double fall_time{};
    double impact_speed{};
    double max_omega{};
    double extrapolation_fraction{};
    double rotor_mass{};
    double total_mass{};
    double mean_prandtl_loss_factor{1.0};
    double mean_axial_induction{};
    double induction_failure_fraction{};
};

struct SimulationSample {
    double time{};
    double height{};
    double down_speed{};
    double omega{};
    double axial_force{};
    double aero_torque{};
    double mean_prandtl_loss_factor{1.0};
    double mean_axial_induction{};
    double induction_failure_fraction{};
};

struct ObjectiveConfig {
    double maximum_omega{2500.0};
    double omega_penalty_scale{1.0e-3};
    double extrapolation_penalty_scale{20.0};
    double induction_failure_penalty_scale{50.0};
    double invalid_result_penalty{1.0e6};
};

struct OptimizationConfig {
    static constexpr std::size_t variable_count = 5;

    std::array<double, variable_count> lower_bounds{
        0.12, 0.015, 0.010, -0.60, -0.60
    };
    std::array<double, variable_count> upper_bounds{
        0.45, 0.100, 0.080, 0.25, 0.60
    };
    std::array<double, variable_count> initial_values{
        0.25, 0.055, 0.025, -0.12, -0.15
    };
    int maximum_evaluations{500};
    double relative_x_tolerance{1.0e-3};
    ObjectiveConfig objective{};
};
