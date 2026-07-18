#include "aero_client.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

namespace {
struct PolarRow {
    std::string airfoil;
    double alpha;
    double reynolds;
    double mach;
    AeroCoefficients coefficients;
};

std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, ',')) {
        fields.push_back(field);
    }
    return fields;
}

void sort_unique(std::vector<double>& values) {
    std::sort(values.begin(), values.end());
    values.erase(std::unique(values.begin(), values.end()), values.end());
}

struct Bracket {
    std::size_t lower;
    std::size_t upper;
    double fraction;
    bool extrapolated;
};

Bracket bracket(const std::vector<double>& axis, double value, bool logarithmic = false) {
    const double transformed = logarithmic ? std::log10(std::max(value, 1.0)) : value;
    const auto transform = [logarithmic](double x) {
        return logarithmic ? std::log10(x) : x;
    };

    if (value <= axis.front()) {
        return {0, 0, 0.0, value < axis.front()};
    }
    if (value >= axis.back()) {
        const auto last = axis.size() - 1;
        return {last, last, 0.0, value > axis.back()};
    }

    const auto upper_it = std::upper_bound(axis.begin(), axis.end(), value);
    const auto upper = static_cast<std::size_t>(upper_it - axis.begin());
    const auto lower = upper - 1;
    const double lo = transform(axis[lower]);
    const double hi = transform(axis[upper]);
    return {lower, upper, (transformed - lo) / (hi - lo), false};
}

double blend(double lower, double upper, double fraction) {
    return lower + (upper - lower) * fraction;
}
} // namespace

AeroClient::AeroClient(const std::filesystem::path& polar_path) {
    std::ifstream input(polar_path);
    if (!input) {
        throw std::runtime_error("Unable to open aerodynamic polar table: " + polar_path.string());
    }

    std::vector<PolarRow> rows;
    std::string line;
    bool saw_header = false;
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }
        if (line.rfind("# backend=", 0) == 0) {
            backend_ = line.substr(10);
            continue;
        }
        if (line.front() == '#') {
            continue;
        }
        if (!saw_header) {
            if (line != "airfoil,alpha_deg,reynolds,mach,cl,cd,cm,confidence") {
                throw std::runtime_error("Unexpected aerodynamic polar header");
            }
            saw_header = true;
            continue;
        }

        const auto fields = split_csv(line);
        if (fields.size() != 8) {
            throw std::runtime_error("Malformed aerodynamic polar row: " + line);
        }
        PolarRow row;
        row.airfoil = fields[0];
        row.alpha = std::stod(fields[1]);
        row.reynolds = std::stod(fields[2]);
        row.mach = std::stod(fields[3]);
        row.coefficients = {std::stod(fields[4]), std::stod(fields[5]),
                            std::stod(fields[6]), std::stod(fields[7])};
        rows.push_back(row);
        alphas_.push_back(row.alpha);
        reynolds_.push_back(row.reynolds);
        machs_.push_back(row.mach);
    }

    if (backend_.empty()) {
        throw std::runtime_error("Polar table is missing required '# backend=' metadata");
    }
    if (rows.empty()) {
        throw std::runtime_error("Aerodynamic polar table contains no data");
    }

    airfoil_ = rows.front().airfoil;
    sort_unique(alphas_);
    sort_unique(reynolds_);
    sort_unique(machs_);
    const auto expected = alphas_.size() * reynolds_.size() * machs_.size();
    if (rows.size() != expected) {
        throw std::runtime_error("Aerodynamic polar table must be a complete regular grid");
    }

    coefficients_.resize(expected);
    std::vector<bool> populated(expected, false);
    for (const auto& row : rows) {
        if (row.airfoil != airfoil_) {
            throw std::runtime_error("A polar table may contain only one airfoil");
        }
        const auto ai = static_cast<std::size_t>(
            std::lower_bound(alphas_.begin(), alphas_.end(), row.alpha) - alphas_.begin());
        const auto ri = static_cast<std::size_t>(
            std::lower_bound(reynolds_.begin(), reynolds_.end(), row.reynolds) - reynolds_.begin());
        const auto mi = static_cast<std::size_t>(
            std::lower_bound(machs_.begin(), machs_.end(), row.mach) - machs_.begin());
        const auto flat = index(ai, ri, mi);
        if (populated[flat]) {
            throw std::runtime_error("Duplicate point in aerodynamic polar table");
        }
        coefficients_[flat] = row.coefficients;
        populated[flat] = true;
    }
}

std::size_t AeroClient::index(std::size_t alpha_i, std::size_t reynolds_i,
                              std::size_t mach_i) const {
    return (alpha_i * reynolds_.size() + reynolds_i) * machs_.size() + mach_i;
}

AeroCoefficients AeroClient::interpolate(const AeroQuery& query) const {
    if (query.airfoil != airfoil_) {
        throw std::runtime_error("Requested airfoil '" + query.airfoil +
                                 "' does not match loaded polar '" + airfoil_ + "'");
    }

    const auto a = bracket(alphas_, query.alpha_deg);
    const auto r = bracket(reynolds_, query.reynolds, true);
    const auto m = bracket(machs_, query.mach);

    const auto interpolate_field = [&](auto member) {
        const auto at = [&](std::size_t ai, std::size_t ri, std::size_t mi) {
            return coefficients_[index(ai, ri, mi)].*member;
        };
        const double c000 = at(a.lower, r.lower, m.lower);
        const double c001 = at(a.lower, r.lower, m.upper);
        const double c010 = at(a.lower, r.upper, m.lower);
        const double c011 = at(a.lower, r.upper, m.upper);
        const double c100 = at(a.upper, r.lower, m.lower);
        const double c101 = at(a.upper, r.lower, m.upper);
        const double c110 = at(a.upper, r.upper, m.lower);
        const double c111 = at(a.upper, r.upper, m.upper);
        const double c00 = blend(c000, c001, m.fraction);
        const double c01 = blend(c010, c011, m.fraction);
        const double c10 = blend(c100, c101, m.fraction);
        const double c11 = blend(c110, c111, m.fraction);
        return blend(blend(c00, c01, r.fraction), blend(c10, c11, r.fraction), a.fraction);
    };

    AeroCoefficients result{
        interpolate_field(&AeroCoefficients::cl),
        interpolate_field(&AeroCoefficients::cd),
        interpolate_field(&AeroCoefficients::cm),
        interpolate_field(&AeroCoefficients::confidence)
    };
    if (a.extrapolated || r.extrapolated || m.extrapolated) {
        result.confidence = 0.0;
    }
    result.confidence = std::clamp(result.confidence, 0.0, 1.0);
    return result;
}

AeroCoefficients AeroClient::evaluate(const AeroQuery& query) const {
    return interpolate(query);
}
