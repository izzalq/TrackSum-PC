#include "graph_types.h"

#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
using namespace std;
namespace tracks {
string find_routes_json(const Graph&, const string&, const string&, int);

static string unescape(const string& s) {
    string out;
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '\\' && i + 1 < s.size()) {
            char n = s[++i];
            out += n == 'n' ? '\n' : n == 'r' ? '\r' : n == 't' ? '\t' : n;
        } else {
            out += s[i];
        }
    }
    return out;
}

static string get_string(const string& json, size_t start, size_t end, const string& key) {
    string needle = "\"" + key + "\"";
    size_t p = json.find(needle, start);
    if (p == string::npos || p >= end) return "";
    p = json.find(':', p + needle.size());
    if (p == string::npos || p >= end) return "";
    p = json.find('"', p + 1);
    if (p == string::npos || p >= end) return "";
    ++p;
    size_t q = json.find('"', p);
    if (q == string::npos || q >= end) return "";
    return unescape(json.substr(p, q - p));
}

static double get_number(const string& json, size_t start, size_t end, const string& key) {
    string needle = "\"" + key + "\"";
    size_t p = json.find(needle, start);
    if (p == string::npos || p >= end) return 0.0;
    p = json.find(':', p + needle.size());
    if (p == string::npos || p >= end) return 0.0;
    p = json.find_first_of("-0123456789", p + 1);
    if (p == string::npos || p >= end) return 0.0;
    try {
        return stod(json.substr(p, end - p));
    } catch (...) {
        return 0.0;
    }
}

static vector<int> get_integer_array(
    const string& json, size_t start, size_t end, const string& key) {
    vector<int> values;
    string needle = "\"" + key + "\"";
    size_t p = json.find(needle, start);
    if (p == string::npos || p >= end) return values;
    p = json.find('[', p + needle.size());
    if (p == string::npos || p >= end) return values;
    size_t array_end = json.find(']', p + 1);
    if (array_end == string::npos || array_end >= end) return values;

    while (p < array_end) {
        p = json.find_first_of("-0123456789", p + 1);
        if (p == string::npos || p >= array_end) break;
        char* next = nullptr;
        long value = strtol(json.c_str() + p, &next, 10);
        if (next == json.c_str() + p || value < 0 || value > 1439) return {};
        values.push_back(static_cast<int>(value));
        p = static_cast<size_t>(next - json.c_str());
    }
    return values;
}

static bool load_graph(const char* path, Graph& graph) {
    ifstream file(path);
    if (!file) return false;
    ostringstream ss;
    ss << file.rdbuf();
    string json = ss.str();

    size_t stops_section = json.find("\"stops\"");
    size_t routes_section = json.find("\"routes\"", stops_section);
    unordered_map<string, pair<string, string>> route_catalog;
    size_t catalog_section = json.find("\"route_catalog\"");
    if (catalog_section != string::npos) {
        size_t catalog_end = json.find(']', catalog_section);
        size_t catalog_item = json.find('{', catalog_section);
        while (catalog_item != string::npos && catalog_item < catalog_end) {
            size_t item_end = json.find('}', catalog_item);
            string route_id = get_string(json, catalog_item, item_end, "route_id");
            if (!route_id.empty()) {
                string route_code = get_string(json, catalog_item, item_end, "route_code");
                string color_hex = get_string(json, catalog_item, item_end, "color_hex");
                if (color_hex.empty()) {
                    color_hex = get_string(json, catalog_item, item_end, "route_color");
                }
                route_catalog[route_id] = {route_code, color_hex};
            }
            catalog_item = json.find('{', item_end + 1);
        }
    }

    size_t p = stops_section;
    while ((p = json.find('{', p)) != string::npos && p < routes_section) {
        size_t end = json.find('}', p);
        string id = get_string(json, p, end, "id");
        if (!id.empty()) {
            int index = static_cast<int>(graph.stops.size());
            graph.stop_index[id] = index;
            graph.stops.push_back({
                id,
                get_string(json, p, end, "name"),
                get_number(json, p, end, "lat"),
                get_number(json, p, end, "lon")
            });
        }
        p = end + 1;
    }

    graph.adjacency.resize(graph.stops.size());
    p = routes_section;
    while ((p = json.find('{', p)) != string::npos) {
        size_t end = json.find('}', p);
        string route_id = get_string(json, p, end, "route_id");
        if (!route_id.empty()) {
            string route_code = get_string(json, p, end, "route_code");
            string route_name = get_string(json, p, end, "route_name");
            string color_hex = get_string(json, p, end, "color_hex");
            if (color_hex.empty()) {
                color_hex = get_string(json, p, end, "route_color");
            }
            string mode = get_string(json, p, end, "mode");
            string operator_name = get_string(json, p, end, "operator");
            string fare_model = get_string(json, p, end, "fare_model");
            string from = get_string(json, p, end, "from");
            string to = get_string(json, p, end, "to");
            int fare = static_cast<int>(get_number(json, p, end, "fare_rupiah"));
            int minutes = static_cast<int>(get_number(json, p, end, "minutes"));
            int headway = static_cast<int>(get_number(json, p, end, "headway_minutes"));
            vector<int> forward_departures =
                get_integer_array(json, p, end, "departure_minutes");
            vector<int> reverse_departures =
                get_integer_array(json, p, end, "reverse_departure_minutes");
            if (mode.empty()) {
                mode = route_id.compare(0, 6, "DAMRI-") == 0 ? "damri" : "angkot";
            }
            if (operator_name.empty()) operator_name = mode;
            if (fare_model.empty()) {
                fare_model = mode == "angkot" ? "distance_tiered" : "flat";
            }
            auto catalog_entry = route_catalog.find(route_id);
            if (catalog_entry != route_catalog.end()) {
                if (route_code.empty()) route_code = catalog_entry->second.first;
                if (color_hex.empty()) color_hex = catalog_entry->second.second;
            }
            if (route_code.empty()) route_code = route_id;
            if (color_hex.empty()) {
                color_hex = mode == "kereta" ? "#D71920"
                    : mode == "jalan_kaki" ? "#707070"
                    : mode == "damri" ? "#F7941D" : "#4CAF50";
            }
            if (graph.stop_index.count(from) && graph.stop_index.count(to)) {
                int u = graph.stop_index[from];
                int v = graph.stop_index[to];
                graph.adjacency[u].push_back({
                    v, route_id, route_code, route_name, color_hex, mode,
                    operator_name, fare_model, 0.0, minutes, fare, headway,
                    forward_departures
                });
                if (!reverse_departures.empty()) {
                    graph.adjacency[v].push_back({
                        u, route_id, route_code, route_name, color_hex, mode,
                        operator_name, fare_model, 0.0, minutes, fare, headway,
                        reverse_departures
                    });
                }
            }
        }
        p = end + 1;
    }

    size_t bidirectional = json.find("\"bidirectional\"");
    if (bidirectional != string::npos
        && json.find("true", bidirectional) < json.find('}', bidirectional)) {
        auto copy = graph.adjacency;
        for (int u = 0; u < static_cast<int>(graph.stops.size()); ++u) {
            for (const Edge& edge : copy[u]) {
                if (!edge.departure_minutes.empty()) continue;
                graph.adjacency[edge.to].push_back(
                    {u, edge.route_id, edge.route_code, edge.route_name,
                     edge.color_hex, edge.mode, edge.operator_name, edge.fare_model,
                     edge.distance_km, edge.base_minutes, edge.fare_rupiah,
                     edge.headway_minutes, edge.departure_minutes});
            }
        }
    }
    return !graph.stops.empty();
}
}

static tracks::Graph g_graph;
static bool g_loaded = false;
static string g_output;

#if defined(_WIN32)
#define TRACKSUM_EXPORT extern "C" __declspec(dllexport)
#else
#define TRACKSUM_EXPORT extern "C" __attribute__((visibility("default")))
#endif

TRACKSUM_EXPORT bool TrackSumLoadGraph(const char* json_path) {
    g_graph = tracks::Graph();
    g_loaded = tracks::load_graph(json_path, g_graph);
    return g_loaded;
}

TRACKSUM_EXPORT const char* TrackSumFindRoutes(
    const char* start_id, const char* goal_id, int departure_hhmm) {
    g_output = g_loaded
        ? tracks::find_routes_json(g_graph, start_id ? start_id : "",
                                   goal_id ? goal_id : "", departure_hhmm)
        : "{\"error\":\"Graf belum dimuat\",\"routes\":[]}";
    return g_output.c_str();
}

TRACKSUM_EXPORT const char* TrackSumListStops() {
    if (!g_loaded) {
        g_output = "[]";
        return g_output.c_str();
    }
    ostringstream out;
    out << "[";
    for (size_t i = 0; i < g_graph.stops.size(); ++i) {
        if (i > 0) out << ",";
        const auto& stop = g_graph.stops[i];
        out << "{\"id\":\"" << stop.id << "\",\"name\":\"" << stop.name
            << "\",\"lat\":" << stop.lat << ",\"lon\":" << stop.lon << "}";
    }
    out << "]";
    g_output = out.str();
    return g_output.c_str();
}

TRACKSUM_EXPORT void TrackSumFreeString(const char*) {}
