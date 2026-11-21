import ctypes
import json
import platform
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EngineLoader:
    def __init__(self):
        if platform.system() == "Windows":
            candidates = [
                ROOT / "core_engine" / "tracksum_engine.dll",
                ROOT / "tracksum_engine.dll",
            ]
        else:
            candidates = [
                ROOT / "core_engine" / "libtracksum_engine.so",
                ROOT / "libtracksum_engine.so",
            ]

        self.lib = None
        for candidate in candidates:
            if candidate.exists():
                self.lib = ctypes.CDLL(str(candidate))
                break

        if self.lib is None:
            raise RuntimeError(
                "Library native belum ditemukan. Jalankan core_engine/build.bat "
                "di Windows atau g++ -shared -fPIC -o core_engine/libtracksum_engine.so "
                "core_engine/pareto_dijkstra.cpp core_engine/bridge.cpp"
            )

        self.lib.TrackSumLoadGraph.argtypes = [ctypes.c_char_p]
        self.lib.TrackSumLoadGraph.restype = ctypes.c_bool
        self.lib.TrackSumListStops.argtypes = []
        self.lib.TrackSumListStops.restype = ctypes.c_char_p
        self.lib.TrackSumFindRoutes.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int
        ]
        self.lib.TrackSumFindRoutes.restype = ctypes.c_char_p
        self.lib.TrackSumFreeString.argtypes = [ctypes.c_char_p]
        self.lib.TrackSumFreeString.restype = None

        data_path = ROOT / "data" / "bandung_routes.json"
        if not self.lib.TrackSumLoadGraph(str(data_path).encode("utf-8")):
            raise RuntimeError("Gagal memuat graf Bandung.")

    @staticmethod
    def parse_hhmm(value):
        if not re.fullmatch(r"\d{2}:\d{2}", value):
            raise ValueError("Format jam harus HH:MM.")
        hours, minutes = map(int, value.split(":"))
        if hours > 23 or minutes > 59:
            raise ValueError("Jam berangkat tidak valid.")
        return hours * 100 + minutes

    def list_stops(self):
        raw = self.lib.TrackSumListStops()
        return json.loads(raw.decode("utf-8"))

    def find_routes(self, start_id, goal_id, departure="07:30"):
        raw = self.lib.TrackSumFindRoutes(
            start_id.encode("utf-8"),
            goal_id.encode("utf-8"),
            self.parse_hhmm(departure),
        )
        result = json.loads(raw.decode("utf-8"))
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result.get("routes", [])
