#include "aero_client.hpp"
#include "optimizer.hpp"
#include "rotor_model.hpp"

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void require_near(double actual, double expected, double tolerance,
                  const std::string& message) {
    require(std::abs(actual - expected) <= tolerance,
            message + ": expected " + std::to_string(expected) +
            ", got " + std::to_string(actual));
}

std::filesystem::path write_test_polar() {
    const auto path = std::filesystem::temp_directory_path() /
        "autorotation_core_interpolation_test.csv";
    std::ofstream output(path);
    output << "# backend=test\n"
              "airfoil,alpha_deg,reynolds,mach,cl,cd,cm,confidence\n";
    for (int alpha_index = 0; alpha_index < 2; ++alpha_index) {
        for (int reynolds_index = 0; reynolds_index < 2; ++reynolds_index) {
            for (int mach_index = 0; mach_index < 2; ++mach_index) {
                const double value = alpha_index + 10.0 * reynolds_index +
                                     100.0 * mach_index;
                output << "NACA0012," << 10 * alpha_index << ','
                       << (reynolds_index == 0 ? 1000 : 100000) << ','
                       << 0.1 * mach_index << ',' << value << ','
                       << value + 1.0 << ',' << value + 2.0 << ",0.8\n";
            }
        }
    }
    return path;
}

void test_aero_interpolation() {
    const auto polar_path = write_test_polar();
    const AeroClient aero(polar_path);
    const auto midpoint = aero.evaluate({"NACA0012", 5.0, 10000.0, 0.05});
    require_near(midpoint.cl, 55.5, 1.0e-12, "trilinear/log-Re interpolation");
    require_near(midpoint.cd, 56.5, 1.0e-12, "drag interpolation");
    require_near(midpoint.confidence, 0.8, 1.0e-12, "in-grid confidence");

    const auto clamped = aero.evaluate({"NACA0012", -1.0, 10000.0, 0.05});
    require_near(clamped.confidence, 0.0, 0.0, "out-of-grid confidence");
    std::filesystem::remove(polar_path);
}

void test_objective_scoring() {
    SimulationResult result{
        .completed = true,
        .valid = true,
        .fall_time = 10.0,
        .max_omega = 2600.0,
        .extrapolation_fraction = 0.1,
        .induction_failure_fraction = 0.02,
    };
    require_near(score_simulation(result), -6.9, 1.0e-12,
                 "objective and penalties");
    result.valid = false;
    require_near(score_simulation(result), 1.0e6, 0.0, "invalid result penalty");
}

void test_geometry_decode_contract() {
    const RotorGeometry geometry = decode_geometry(
        {0.3, 0.06, 0.03, -0.1, 0.2}, "NACA2412");
    require_near(geometry.radius, 0.3, 0.0, "decoded radius");
    require(geometry.airfoil == "NACA2412", "decoded airfoil");
    bool rejected = false;
    try {
        static_cast<void>(decode_geometry({0.3}, "NACA2412"));
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    require(rejected, "wrong-sized design vector must be rejected");
}

void test_model_validation_and_mass() {
    const auto polar_path = std::filesystem::path(AUTOROTATION_SOURCE_DIR) /
                            "data/aero_polar.csv";
    const AeroClient aero(polar_path);
    RotorModel model(Environment{}, SimulationConfig{}, aero);
    RotorGeometry invalid;
    invalid.radius = invalid.root_cutout;
    require(!model.simulate(invalid).valid, "invalid geometry must be rejected");

    RotorGeometry thin;
    thin.airfoil = aero.airfoil();
    const auto thin_mass = model.mass_properties(thin);
    const auto thin_result = model.simulate(thin);
    require(thin_result.valid, "default geometry should be valid");
    require(thin_result.rotor_mass > 0.0, "blade mass must be included");
    require_near(thin_result.rotor_mass, thin_mass.mass, 1.0e-12,
                 "reported and reusable mass calculations must agree");
    require(thin_result.total_mass > thin_result.rotor_mass,
            "body mass must be added to rotor mass");

    RotorGeometry thick = thin;
    thick.airfoil = "NACA2418";
    const auto thick_mass = model.mass_properties(thick);
    require(thick_mass.mass > thin_mass.mass,
            "thicker sections must increase printed blade mass");
    require(thick_mass.inertia > thin_mass.inertia,
            "thicker sections must increase rotor inertia");

    bool rejected = false;
    try {
        static_cast<void>(model.simulate(thick));
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    require(rejected, "mismatched aerodynamic table must be rejected");
}
} // namespace

int main() {
    try {
        test_aero_interpolation();
        test_objective_scoring();
        test_geometry_decode_contract();
        test_model_validation_and_mass();
        std::cout << "All autorotation core tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Test failure: " << error.what() << '\n';
        return 1;
    }
}
