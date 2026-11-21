import json
import math
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
IP_GEOLOCATION_URL = "https://ipapi.co/json/"
VIEWBOX = "107.45,-6.75,107.85,-7.10"
DEFAULT_USER_AGENT = (
    "TrackSum-PC/1.0 (+https://github.com/izzalq/TrackSum-PC)"
)


class LocationServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    lat: float
    lon: float
    source: str
    category: str = ""


@dataclass(frozen=True)
class PlaceSearchResult:
    places: list[Place]
    remote_error: Optional[str] = None


class LocationService:
    def __init__(
        self,
        local_stops: Optional[list[dict]] = None,
        timeout: float = 8.0,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Callable = urlopen,
        min_nominatim_interval: float = 1.0,
    ):
        self.timeout = float(timeout)
        if self.timeout <= 0:
            raise ValueError("timeout harus lebih besar dari 0.")
        if not user_agent.strip():
            raise ValueError("User-Agent tidak boleh kosong.")
        self.user_agent = user_agent
        self._opener = opener
        self._min_nominatim_interval = max(0.0, float(min_nominatim_interval))
        self._nominatim_lock = threading.Lock()
        self._last_nominatim_request = 0.0
        self.local_stops = (
            self._load_local_stops() if local_stops is None
            else [self._as_local_place(stop) for stop in local_stops]
        )

    @staticmethod
    def _coordinates(lat, lon):
        try:
            latitude = float(lat)
            longitude = float(lon)
        except (TypeError, ValueError) as exc:
            raise LocationServiceError("Koordinat lokasi tidak valid.") from exc
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise LocationServiceError("Koordinat lokasi di luar rentang valid.")
        return latitude, longitude

    @classmethod
    def _as_local_place(cls, stop: dict) -> Place:
        lat, lon = cls._coordinates(stop["lat"], stop["lon"])
        return Place(
            id=str(stop["id"]),
            name=str(stop["name"]),
            lat=lat,
            lon=lon,
            source="local",
            category=stop.get("stop_type", "halte"),
        )

    def _load_local_stops(self) -> list[Place]:
        path = ROOT / "data" / "bandung_routes.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stops = data["stops"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LocationServiceError(
                "Gagal memuat daftar halte lokal dari data/bandung_routes.json."
            ) from exc
        return [self._as_local_place(stop) for stop in stops]

    @staticmethod
    def _normalize(value):
        return unicodedata.normalize("NFKC", value).strip().casefold()

    def search_local(self, query: str, limit: int = 8) -> list[Place]:
        if limit < 1:
            raise ValueError("limit harus minimal 1.")
        normalized_query = self._normalize(query)
        if not normalized_query:
            return []
        matches = []
        for place in self.local_stops:
            name = self._normalize(place.name)
            if normalized_query in name:
                priority = 0 if name == normalized_query else (
                    1 if name.startswith(normalized_query) else 2
                )
                matches.append((priority, name, place))
        matches.sort(key=lambda match: (match[0], match[1]))
        return [match[2] for match in matches[:limit]]

    def _request_json(self, request: Request, provider: str):
        try:
            with self._opener(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (
            HTTPError, URLError, TimeoutError, OSError, ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise LocationServiceError(
                "{} request gagal: {}".format(provider, exc)
            ) from exc

    def _nominatim_json(self, request: Request):
        with self._nominatim_lock:
            elapsed = time.monotonic() - self._last_nominatim_request
            if elapsed < self._min_nominatim_interval:
                time.sleep(self._min_nominatim_interval - elapsed)
            self._last_nominatim_request = time.monotonic()
            return self._request_json(request, "Nominatim")

    def search_nominatim(self, query: str, limit: int = 8) -> list[Place]:
        if limit < 1:
            raise ValueError("limit harus minimal 1.")
        query = query.strip()
        if not query:
            return []
        params = urlencode({
            "q": query,
            "format": "jsonv2",
            "limit": min(int(limit), 10),
            "viewbox": VIEWBOX,
            "bounded": 1,
            "addressdetails": 1,
        })
        request = Request(
            "{}?{}".format(NOMINATIM_SEARCH_URL, params),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Language": "id,en",
            },
        )
        response = self._nominatim_json(request)
        if not isinstance(response, list):
            raise LocationServiceError("Respons pencarian Nominatim tidak valid.")
        places = []
        for item in response:
            try:
                lat, lon = self._coordinates(item["lat"], item["lon"])
                name = item.get("display_name", "").strip()
                if not name:
                    continue
                place_id = "{}:{}".format(
                    item.get("osm_type", "osm"), item.get("osm_id", "")
                )
                category = item.get("type") or item.get("class", "")
            except (KeyError, TypeError, AttributeError):
                continue
            places.append(Place(
                id=place_id,
                name=name,
                lat=lat,
                lon=lon,
                source="nominatim",
                category=category,
            ))
        return places

    @staticmethod
    def _same_place(first, second):
        first_name = LocationService._normalize(first.name)
        second_name = LocationService._normalize(second.name)
        if not first_name or not second_name:
            return False
        names_match = (
            first_name == second_name
            or first_name in second_name
            or second_name in first_name
        )
        if not names_match:
            return False
        lat_delta = math.radians(first.lat - second.lat)
        lon_delta = math.radians(first.lon - second.lon)
        haversine = (
            math.sin(lat_delta / 2) ** 2
            + math.cos(math.radians(first.lat))
            * math.cos(math.radians(second.lat))
            * math.sin(lon_delta / 2) ** 2
        )
        return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(haversine))) < 0.25

    def search_places(self, query: str, limit: int = 8) -> PlaceSearchResult:
        query = query.strip()
        if not query:
            return PlaceSearchResult([])
        local_places = self.search_local(query, limit)
        try:
            remote_places = self.search_nominatim(query, limit)
        except LocationServiceError as exc:
            return PlaceSearchResult(local_places[:limit], str(exc))

        places = list(local_places)
        for remote in remote_places:
            if not any(self._same_place(remote, local) for local in places):
                places.append(remote)
            if len(places) >= limit:
                break
        return PlaceSearchResult(places[:limit])

    def reverse_geocode(self, lat: float, lon: float) -> Place:
        latitude, longitude = self._coordinates(lat, lon)
        params = urlencode({
            "format": "jsonv2",
            "lat": "{:.7f}".format(latitude),
            "lon": "{:.7f}".format(longitude),
            "zoom": 18,
            "addressdetails": 1,
        })
        request = Request(
            "{}?{}".format(NOMINATIM_REVERSE_URL, params),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Language": "id,en",
            },
        )
        response = self._nominatim_json(request)
        if not isinstance(response, dict) or not response.get("display_name"):
            raise LocationServiceError(
                "Nominatim tidak menemukan nama tempat untuk koordinat tersebut."
            )
        osm_id = response.get("osm_id", "")
        osm_type = response.get("osm_type", "osm")
        return Place(
            id="{}:{}".format(osm_type, osm_id),
            name=response["display_name"],
            lat=latitude,
            lon=longitude,
            source="nominatim_reverse",
            category=response.get("type") or response.get("class", ""),
        )

    def _device_gps_location(self, timeout: float) -> Place:
        try:
            from plyer import gps
        except ImportError as exc:
            raise LocationServiceError("Plyer GPS tidak tersedia.") from exc

        completed = threading.Event()
        result = {}

        def on_location(**kwargs):
            try:
                result["coordinates"] = self._coordinates(
                    kwargs.get("lat"), kwargs.get("lon")
                )
            except LocationServiceError as exc:
                result["error"] = str(exc)
            completed.set()

        try:
            gps.configure(on_location=on_location)
            gps.start(minTime=1000, minDistance=0)
            if not completed.wait(timeout):
                raise LocationServiceError("GPS tidak memberi lokasi sebelum timeout.")
        except LocationServiceError:
            raise
        except (AttributeError, NotImplementedError, OSError, RuntimeError, TypeError) as exc:
            raise LocationServiceError("GPS perangkat gagal: {}".format(exc)) from exc
        finally:
            try:
                gps.stop()
            except (AttributeError, NotImplementedError, OSError, RuntimeError):
                pass

        if "error" in result:
            raise LocationServiceError("GPS mengembalikan " + result["error"])
        lat, lon = result["coordinates"]
        return Place(
            id="current-device",
            name="Lokasi perangkat",
            lat=lat,
            lon=lon,
            source="gps",
        )

    def _ip_location(self) -> Place:
        request = Request(
            IP_GEOLOCATION_URL,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        response = self._request_json(request, "IP geolocation")
        if not isinstance(response, dict):
            raise LocationServiceError("Respons IP geolocation tidak valid.")
        lat, lon = self._coordinates(
            response.get("latitude"), response.get("longitude")
        )
        area = ", ".join(filter(None, (
            response.get("city"),
            response.get("region"),
            response.get("country_name"),
        )))
        return Place(
            id="current-ip",
            name="Lokasi perkiraan via IP" + (": " + area if area else ""),
            lat=lat,
            lon=lon,
            source="ip",
        )

    def get_current_location(self, timeout: float = 12.0) -> Place:
        timeout = float(timeout)
        if timeout <= 0:
            raise ValueError("timeout harus lebih besar dari 0.")
        try:
            return self._device_gps_location(timeout)
        except LocationServiceError as gps_error:
            try:
                return self._ip_location()
            except LocationServiceError as ip_error:
                raise LocationServiceError(
                    "Lokasi perangkat tidak tersedia ({}); fallback IP gagal ({})."
                    .format(gps_error, ip_error)
                ) from ip_error
