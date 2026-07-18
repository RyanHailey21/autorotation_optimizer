#pragma once

#include "types.hpp"

#include <filesystem>
#include <string>
#include <vector>

class AeroClient {
public:
    explicit AeroClient(const std::filesystem::path& polar_path);

    AeroCoefficients evaluate(const AeroQuery& query) const;
    const std::string& backend() const { return backend_; }
    const std::string& airfoil() const { return airfoil_; }

private:
    std::string backend_;
    std::string airfoil_;
    std::vector<double> alphas_;
    std::vector<double> reynolds_;
    std::vector<double> machs_;
    std::vector<AeroCoefficients> coefficients_;

    std::size_t index(std::size_t alpha_i, std::size_t reynolds_i,
                      std::size_t mach_i) const;
    AeroCoefficients interpolate(const AeroQuery& query) const;
};
