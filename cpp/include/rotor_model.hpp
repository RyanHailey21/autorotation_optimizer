#pragma once

#include "aero_client.hpp"
#include "types.hpp"

#include <vector>

class RotorModel {
public:
    struct RotorMassProperties {
        double mass;
        double inertia;
    };

    RotorModel(Environment env, SimulationConfig cfg, AeroClient aero);

    RotorMassProperties mass_properties(const RotorGeometry& geometry) const;
    SimulationResult simulate(const RotorGeometry& geometry) const;
    SimulationResult simulate_with_trace(const RotorGeometry& geometry,
                                         std::vector<SimulationSample>& trace) const;

private:
    Environment env_;
    SimulationConfig cfg_;
    AeroClient aero_;

    static double lerp(double a, double b, double t);
    static double airfoil_area_coefficient(const std::string& airfoil);
    template<bool RecordTrace>
    SimulationResult simulate_impl(const RotorGeometry& geometry,
                                   std::vector<SimulationSample>* trace) const;
};
