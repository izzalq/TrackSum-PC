#pragma once

#include <string>
#include <unordered_map>
#include <vector>

namespace tracks {

struct Stop {
    std::string id;
    std::string name;
    double lat;
    double lon;
};

struct Edge {
    int to;
    std::string route_id;
    std::string route_code;
    std::string route_name;
    std::string color_hex;
    std::string mode;
    std::string operator_name;
    std::string fare_model;
    double distance_km;
    int base_minutes;
    int fare_rupiah;
    int headway_minutes;
    std::vector<int> departure_minutes;
};

struct Graph {
    std::vector<Stop> stops;
    std::unordered_map<std::string, int> stop_index;
    std::vector<std::vector<Edge>> adjacency;
};

} // namespace tracks
