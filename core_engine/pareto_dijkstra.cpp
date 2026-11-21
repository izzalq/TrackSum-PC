#include "graph_types.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

using namespace std;
namespace tracks {

struct Label {
    int stop;
    double cost_minutes;
    double cost_fare;
    string last_route_id;
    vector<int> nodes;
    vector<const Edge*> edges;
    bool active = true;
};

using PathKey = pair<vector<int>, vector<string>>;

static PathKey path_key(const Label& label) {
    vector<string> route_ids;
    route_ids.reserve(label.edges.size());
    for (const Edge* edge : label.edges) route_ids.push_back(edge->route_id);
    return {label.nodes, route_ids};
}

static double haversine_km(double lat1, double lon1, double lat2, double lon2) {
    constexpr double pi = 3.14159265358979323846;
    constexpr double earth_km = 6371.0;
    double dlat = (lat2 - lat1) * pi / 180.0;
    double dlon = (lon2 - lon1) * pi / 180.0;
    double a = sin(dlat / 2.0) * sin(dlat / 2.0)
        + cos(lat1 * pi / 180.0) * cos(lat2 * pi / 180.0)
        * sin(dlon / 2.0) * sin(dlon / 2.0);
    return earth_km * 2.0 * atan2(sqrt(a), sqrt(max(0.0, 1.0 - a)));
}

static bool pareto_dominates(const Label& a, const Label& b) {
    if (a.last_route_id != b.last_route_id) return false;
    return a.cost_minutes <= b.cost_minutes && a.cost_fare <= b.cost_fare
        && (a.cost_minutes < b.cost_minutes || a.cost_fare < b.cost_fare);
}

static double edge_fare(const Edge& edge, const string& last_route_id) {
    if (edge.fare_model == "flat" && edge.route_id == last_route_id) return 0.0;
    return edge.fare_rupiah;
}

static double edge_wait_minutes(
    const Edge& edge, const string& last_route_id, int departure_hhmm,
    double elapsed_minutes) {
    if (edge.route_id == last_route_id) return 0.0;
    const double departure_minutes =
        departure_hhmm / 100 * 60 + departure_hhmm % 100;
    const double current_time = departure_minutes + elapsed_minutes;
    if (!edge.departure_minutes.empty()) {
        double next_departure = numeric_limits<double>::infinity();
        const double day_start = floor(current_time / 1440.0) * 1440.0;
        for (int scheduled : edge.departure_minutes) {
            double candidate = day_start + scheduled;
            if (candidate + 1e-9 < current_time) candidate += 1440.0;
            next_departure = min(next_departure, candidate);
        }
        return next_departure - current_time;
    }
    if (edge.headway_minutes > 0) return edge.headway_minutes / 2.0;
    return 0.0;
}

static double edge_travel_minutes(
    const Edge& edge, const Graph& graph, int from, int departure_hhmm,
    const string& last_route_id, double elapsed_minutes) {
    double road_adjustment = 0.0;
    if (edge.mode != "kereta" && edge.mode != "jalan_kaki") {
        road_adjustment = haversine_km(
            graph.stops[from].lat, graph.stops[from].lon,
            graph.stops[edge.to].lat, graph.stops[edge.to].lon) * 0.15;
    }
    return edge_wait_minutes(edge, last_route_id, departure_hhmm, elapsed_minutes)
        + edge.base_minutes + road_adjustment;
}

static string json_escape(const string& value) {
    ostringstream out;
    for (unsigned char c : value) {
        switch (c) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (c < 0x20) out << "\\u" << hex << static_cast<int>(c) << dec;
            else out << c;
        }
    }
    return out.str();
}

static vector<Label> pareto_labels(
    const Graph& graph, int start, int goal, int departure_hhmm) {
    vector<Label> labels;
    vector<vector<size_t>> frontier(graph.stops.size());
    priority_queue<pair<double, size_t>, vector<pair<double, size_t>>,
        greater<pair<double, size_t>>> pending;
    Label initial{start, 0.0, 0.0, "", {start}, {}};
    labels.push_back(initial);
    frontier[start].push_back(0);
    pending.push({0.0, 0});

    vector<Label> all_goal;
    while (!pending.empty()) {
        auto [_, label_index] = pending.top();
        pending.pop();
        if (!labels[label_index].active) continue;
        const Label label = labels[label_index];
        const int u = label.stop;
        if (u == goal) {
            all_goal.push_back(label);
            continue;
        }

        for (const Edge& edge : graph.adjacency[u]) {
            double minutes = edge_travel_minutes(
                edge, graph, u, departure_hhmm, label.last_route_id,
                label.cost_minutes);
            double fare = edge_fare(edge, label.last_route_id);
            Label next{edge.to,
                label.cost_minutes + minutes,
                label.cost_fare + fare,
                edge.route_id,
                label.nodes,
                label.edges};
            next.nodes.push_back(edge.to);
            next.edges.push_back(&edge);

            bool dominated = false;
            for (size_t existing_index : frontier[edge.to]) {
                const Label& existing = labels[existing_index];
                if (existing.active && pareto_dominates(existing, next)) {
                    dominated = true;
                    break;
                }
            }
            if (dominated) continue;

            for (size_t existing_index : frontier[edge.to]) {
                Label& existing = labels[existing_index];
                if (existing.active && pareto_dominates(next, existing)) {
                    existing.active = false;
                }
            }
            size_t next_index = labels.size();
            labels.push_back(std::move(next));
            frontier[edge.to].push_back(next_index);
            pending.push({
                labels[next_index].cost_minutes + labels[next_index].cost_fare / 100.0,
                next_index
            });
        }
    }
    return all_goal;
}

static vector<Label> simple_paths(
    const Graph& graph, int start, int goal, int departure_hhmm) {
    vector<Label> paths;
    vector<bool> visited(graph.stops.size(), false);
    Label initial{start, 0.0, 0.0, "", {start}, {}};
    visited[start] = true;

    auto visit = [&](auto&& self, const Label& label) -> void {
        if (paths.size() >= 50000) return;
        if (label.stop == goal) {
            paths.push_back(label);
            return;
        }

        for (const Edge& edge : graph.adjacency[label.stop]) {
            if (visited[edge.to]) continue;
            double minutes = edge_travel_minutes(
                edge, graph, label.stop, departure_hhmm, label.last_route_id,
                label.cost_minutes);
            double fare = edge_fare(edge, label.last_route_id);
            Label next{edge.to, label.cost_minutes + minutes,
                label.cost_fare + fare, edge.route_id, label.nodes, label.edges};
            next.nodes.push_back(edge.to);
            next.edges.push_back(&edge);
            visited[edge.to] = true;
            self(self, next);
            visited[edge.to] = false;
        }
    };
    visit(visit, initial);
    return paths;
}

static string format_time(int hhmm, int minutes) {
    int total = hhmm / 100 * 60 + hhmm % 100 + minutes;
    total = (total % 1440 + 1440) % 1440;
    char out[6];
    snprintf(out, sizeof(out), "%02d:%02d", total / 60, total % 60);
    return out;
}

string find_routes_json(const Graph& graph, const string& start_id,
                             const string& goal_id, int departure_hhmm) {
    auto start_it = graph.stop_index.find(start_id);
    auto goal_it = graph.stop_index.find(goal_id);
    if (start_it == graph.stop_index.end() || goal_it == graph.stop_index.end()) {
        return "{\"error\":\"Titik awal atau tujuan tidak ditemukan\",\"routes\":[]}";
    }

    vector<Label> routes =
        pareto_labels(graph, start_it->second, goal_it->second, departure_hhmm);
    vector<Label> alternatives =
        simple_paths(graph, start_it->second, goal_it->second, departure_hhmm);
    set<PathKey> known_paths;
    for (const Label& route : routes) known_paths.insert(path_key(route));
    for (const Label& candidate : alternatives) {
        if (known_paths.insert(path_key(candidate)).second) routes.push_back(candidate);
    }
    sort(routes.begin(), routes.end(), [](const Label& a, const Label& b) {
        if (a.cost_minutes != b.cost_minutes) return a.cost_minutes < b.cost_minutes;
        return a.cost_fare > b.cost_fare;
    });
    set<PathKey> selected_path_keys;
    routes.erase(remove_if(routes.begin(), routes.end(), [&selected_path_keys](const Label& route) {
        return !selected_path_keys.insert(path_key(route)).second;
    }), routes.end());

    vector<Label> selected;
    auto add_best = [&selected, &routes](auto score) {
        const Label* best = nullptr;
        double best_score = numeric_limits<double>::infinity();
        for (const Label& candidate : routes) {
            bool already_selected = false;
            for (const Label& choice : selected) {
                if (path_key(candidate) == path_key(choice)) {
                    already_selected = true;
                    break;
                }
            }
            if (already_selected) continue;
            double value = score(candidate);
            if (value < best_score) {
                best_score = value;
                best = &candidate;
            }
        }
        if (best) selected.push_back(*best);
    };

    add_best([](const Label& route) { return route.cost_minutes; });
    add_best([](const Label& route) { return route.cost_minutes + route.cost_fare / 250.0; });
    add_best([](const Label& route) { return route.cost_fare + route.cost_minutes * 20.0; });
    add_best([](const Label& route) { return route.cost_fare + route.cost_minutes * 0.01; });

    ostringstream out;
    out << "{\"routes\":[";
    for (size_t i = 0; i < selected.size(); ++i) {
        const Label& route = selected[i];
        int duration = static_cast<int>(ceil(route.cost_minutes));
        int fare = static_cast<int>(round(route.cost_fare));
        if (fare == 0 && !route.edges.empty()) {
            for (const Edge* edge : route.edges) fare += static_cast<int>(edge->fare_rupiah);
        }

        if (i > 0) out << ",";
        out << "{";
        out << "\"id\":\"route-" << i + 1 << "\",";
        out << "\"name\":\"" << json_escape(i == 0 ? "Paling Cepat / Mahal" :
            i == 1 ? "Lumayan Cepat" : i == 2 ? "Hemat & Santai" : "Paling Murah / Lambat") << "\",";
        out << "\"duration_minutes\":" << duration << ",";
        out << "\"departure\":\"" << format_time(departure_hhmm, 0) << "\",";
        out << "\"arrival\":\"" << format_time(departure_hhmm, duration) << "\",";
        out << "\"fare_rupiah\":" << fare << ",";
        out << "\"polyline\":[";
        for (size_t n = 0; n < route.nodes.size(); ++n) {
            if (n > 0) out << ",";
            const Stop& stop = graph.stops[route.nodes[n]];
            out << "{\"lat\":" << stop.lat << ",\"lon\":" << stop.lon << ",\"name\":\""
                << json_escape(stop.name) << "\"}";
        }
        out << "],\"steps\":[";
        double elapsed = 0.0;
        string last_route_id;
        for (size_t e = 0; e < route.edges.size(); ++e) {
            const Edge* edge = route.edges[e];
            double wait = edge_wait_minutes(
                *edge, last_route_id, departure_hhmm, elapsed);
            double duration_minutes = edge_travel_minutes(
                *edge, graph, route.nodes[e], departure_hhmm, last_route_id,
                elapsed);
            int step_duration = static_cast<int>(ceil(duration_minutes));
            double charged_fare = edge_fare(*edge, last_route_id);
            if (e > 0) out << ",";
            out << "{\"route_id\":\"" << json_escape(edge->route_id) << "\","
                << "\"route_name\":\"" << json_escape(edge->route_name) << "\","
                << "\"mode\":\"" << json_escape(edge->mode) << "\","
                << "\"operator\":\"" << json_escape(edge->operator_name) << "\","
                << "\"fare_model\":\"" << json_escape(edge->fare_model) << "\","
                << "\"from\":\"" << json_escape(graph.stops[route.nodes[e]].name) << "\","
                << "\"to\":\"" << json_escape(graph.stops[route.nodes[e + 1]].name) << "\","
                << "\"fare_rupiah\":" << static_cast<int>(round(charged_fare)) << ","
                << "\"wait_minutes\":" << static_cast<int>(ceil(wait)) << ","
                << "\"duration_minutes\":" << step_duration << ","
                << "\"departure\":\""
                << format_time(departure_hhmm, static_cast<int>(ceil(elapsed + wait)))
                << "\","
                << "\"arrival\":\""
                << format_time(departure_hhmm, static_cast<int>(ceil(elapsed + duration_minutes)))
                << "\"}";
            last_route_id = edge->route_id;
            elapsed += duration_minutes;
        }
        out << "]";
        out << "}";
    }
    out << "]}";
    return out.str();
}

} // namespace tracks
