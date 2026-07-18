#pragma once

#include "aero_client.hpp"
#include "types.hpp"

class RotorModel {
public:
    RotorModel(Environment env, SimulationConfig cfg, AeroClient aero);

    SimulationResult simulate(const RotorGeometry& geometry) const;

private:
    struct RotorMassProperties {
        double mass;
        double inertia;
    };

    Environment env_;
    SimulationConfig cfg_;
    AeroClient aero_;

    static double lerp(double a, double b, double t);
    static double airfoil_area_coefficient(const std::string& airfoil);
    RotorMassProperties rotor_mass_properties(const RotorGeometry& geometry) const;
};
