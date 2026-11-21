#pragma once

#include <string>
#include <unordered_map>
#include <vector>
using namespace std;
namespace tracks {

struct Stop {
    string id;
    string name;
    double lat;
    double lon;
};

struct Edge {
    int to;
    string route_id;
    std::string route_code;
    string route_name;
    std::string color_hex;
    string mode;
    string operator_name;
    string fare_model;
    double distance_km;
    int base_minutes;
    int fare_rupiah;
    int headway_minutes;
    vector<int> departure_minutes;
};

struct Graph {
    vector<Stop> stops;
    unordered_map<string, int> stop_index;
    vector<vector<Edge>> adjacency;
};

} // namespace tracks
