from datetime import datetime
from pathlib import Path
import json

from PIL import Image, ExifTags


def _rational_to_float(value):
    try:
        return float(value.numerator) / float(value.denominator)
    except AttributeError:
        return float(value)


def extract_exif_metadata(photo_path):
    path = Path(photo_path)
    if not path.exists():
        raise ValueError("File foto tidak ditemukan.")
    if path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("Bukti harus berupa foto JPG/JPEG.")

    with Image.open(path) as image:
        exif_data = image.getexif()
        if not exif_data:
            raise ValueError("Foto tidak memiliki metadata EXIF.")

        exif = {ExifTags.TAGS.get(key, key): value for key, value in exif_data.items()}
        gps = exif.get("GPSInfo")
        timestamp = exif.get("DateTimeOriginal") or exif.get("DateTime")

        if not isinstance(gps, dict):
            gps = {}
        gps_tags = {ExifTags.GPSTAGS.get(key, key): value for key, value in gps.items()}

        lat_ref = gps_tags.get("GPSLatitudeRef")
        lon_ref = gps_tags.get("GPSLongitudeRef")
        lat_values = gps_tags.get("GPSLatitude")
        lon_values = gps_tags.get("GPSLongitude")
        if not all((lat_ref, lon_ref, lat_values, lon_values)):
            raise ValueError("Foto wajib memiliki koordinat GPS di EXIF.")

        def coordinate(values):
            degrees, minutes, seconds = [_rational_to_float(v) for v in values]
            return degrees + minutes / 60.0 + seconds / 3600.0

        latitude = coordinate(lat_values)
        longitude = coordinate(lon_values)
        if lat_ref == "S":
            latitude *= -1
        if lon_ref == "W":
            longitude *= -1

    if not timestamp:
        raise ValueError("Foto wajib memiliki timestamp pengambilan.")
    try:
        datetime.strptime(timestamp, "%Y:%m:%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("Timestamp EXIF tidak valid.") from exc

    return {
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp,
    }


def save_report(report, photo_path, output_path):
    metadata = extract_exif_metadata(photo_path)
    payload = {
        "kind": report.get("kind", "Tarif"),
        "text": report.get("text", ""),
        "route": report.get("route", ""),
        "photo": str(Path(photo_path)),
        "exif": metadata,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
    existing.append(payload)
    output.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
