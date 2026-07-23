"""Shared helpers for Feux de forêt integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import quote

from .const import BASE_URL, RESOLVE_URL, HTTP_USER_AGENT, PROBABLE_STATUTS, BAN_REVERSE_URL

_LOGGER = logging.getLogger(__name__)

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"


def full_url(url):
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{BASE_URL}{url}" if url.startswith("/") else f"{BASE_URL}/{url}"


def commune_from_url(url):
    if not url:
        return None
    slug = url.strip("/").split("/")[-1]
    parts = slug.split("-")
    while parts and parts[-1].isdigit():
        parts.pop()
    return " ".join(p.capitalize() for p in parts) if parts else None


def department_from_url(url):
    if not url:
        return None
    segments = url.strip("/").split("/")
    if not segments:
        return None
    first = segments[0]
    parts = first.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isalnum():
        return parts[1]
    return None


def _extract_department_code(value):
    """Normalise une valeur de département en un code numérique (ou 2A/2B pour la Corse)."""
    if not value:
        return None
    text = str(value).strip().upper()
    if text in ("2A", "2B"):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    if digits[:2] in ("97", "98") and len(digits) >= 3:
        return digits[:3]
    if len(digits) <= 2:
        return digits.zfill(2)
    return None


def normalize_department(value, url=None):
    """Retourne un numéro de département fiable, quelle que soit la source d'origine."""
    code = _extract_department_code(value)
    if code:
        return code
    if url:
        return _extract_department_code(department_from_url(url)) or department_from_url(url)
    return None


def commune_with_department(commune, dept):
    if not commune:
        commune = "Zone inconnue"
    if dept:
        return f"{commune} ({dept})"
    return commune


def relative_path_from_url(url):
    if not url:
        return None
    if url.startswith(BASE_URL):
        url = url[len(BASE_URL):]
    if not url.startswith("/"):
        url = f"/{url}"
    if not url.endswith("/"):
        url = f"{url}/"
    return url


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_point(geometry):
    """Retourne (lat, lng) à partir d'une géométrie GeoJSON, quel que soit son type."""
    if not isinstance(geometry, dict):
        return None, None

    gtype = geometry.get("type")

    if gtype == "GeometryCollection":
        for sub_geom in geometry.get("geometries", []):
            lat, lng = extract_point(sub_geom)
            if lat is not None:
                return lat, lng
        return None, None

    coords = geometry.get("coordinates")
    if not coords:
        return None, None

    if gtype == "Point":
        lng, lat = coords[0], coords[1]
        return _float(lat), _float(lng)

    if gtype == "MultiPoint":
        lng, lat = coords[0][0], coords[0][1]
        return _float(lat), _float(lng)

    if gtype == "LineString":
        return _centroid_of_ring(coords)

    if gtype == "MultiLineString":
        flat_points = [p for line in coords for p in line]
        return _centroid_of_ring(flat_points)

    if gtype == "Polygon":
        ring = coords[0] if coords else []
        return _centroid_of_ring(ring)

    if gtype == "MultiPolygon":
        ring = coords[0][0] if coords and coords[0] else []
        return _centroid_of_ring(ring)

    return None, None


def _centroid_of_ring(ring):
    points = [p for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not points:
        return None, None
    avg_lng = sum(p[0] for p in points) / len(points)
    avg_lat = sum(p[1] for p in points) / len(points)
    return _float(avg_lat), _float(avg_lng)


def _point_from_properties(props):
    """Cherche des coordonnées directement dans les propriétés d'une feature (repli)."""
    if not isinstance(props, dict):
        return None, None

    lat = _float(props.get("lat") or props.get("latitude") or props.get("y"))
    lng = _float(props.get("lng") or props.get("lon") or props.get("longitude") or props.get("x"))
    if lat is not None and lng is not None:
        return lat, lng

    for key in ("position", "coords", "coordonnees", "centre", "center", "location", "point"):
        sub = props.get(key)
        if isinstance(sub, dict):
            lat, lng = _point_from_properties(sub)
            if lat is not None and lng is not None:
                return lat, lng
        if isinstance(sub, (list, tuple)) and len(sub) >= 2:
            lng2, lat2 = _float(sub[0]), _float(sub[1])
            if lat2 is not None and lng2 is not None:
                return lat2, lng2

    return None, None


def extract_point_from_feature(feature):
    """Retourne (lat, lng) pour une feature GeoJSON complète, avec repli sur les propriétés."""
    if not isinstance(feature, dict):
        return None, None

    lat, lng = extract_point(feature.get("geometry"))
    if lat is not None and lng is not None:
        return lat, lng

    return _point_from_properties(feature.get("properties"))


async def _ban_reverse_request(session, lat, lng, geocode_type=None):
    url = f"{BAN_REVERSE_URL}?lon={lng}&lat={lat}"
    if geocode_type:
        url += f"&type={geocode_type}"
    try:
        async with session.get(url, headers={"User-Agent": HTTP_USER_AGENT}, timeout=8) as resp:
            if resp.status != 200:
                _LOGGER.debug("BAN reverse geocode (%s) returned HTTP %s", geocode_type or "default", resp.status)
                return None
            return await resp.json(content_type=None)
    except Exception as err:
        _LOGGER.debug("Failed BAN reverse geocode (%s) for %s,%s: %s", geocode_type or "default", lat, lng, err)
        return None


def _department_code_from_postcode(postcode):
    """Convertit un code postal français en numéro de département à 2 (ou 3) chiffres."""
    if not postcode:
        return None
    digits = "".join(ch for ch in str(postcode) if ch.isdigit())
    if len(digits) < 2:
        return None
    if digits[:2] == "20":
        try:
            code5 = int(digits[:5]) if len(digits) >= 5 else None
        except ValueError:
            code5 = None
        if code5 is not None and 20000 <= code5 <= 20189:
            return "2A"
        return "2B"
    if digits[:2] == "97" or digits[:2] == "98":
        return digits[:3]
    return digits[:2]


async def _nominatim_reverse_request(session, lat, lng):
    """Repli via OpenStreetMap Nominatim quand la BAN ne renvoie rien."""
    url = f"{NOMINATIM_REVERSE_URL}?lat={lat}&lon={lng}&format=jsonv2&zoom=10&accept-language=fr"
    try:
        async with session.get(
            url, headers={"User-Agent": HTTP_USER_AGENT}, timeout=8
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug("Nominatim reverse geocode returned HTTP %s", resp.status)
                return None, None
            payload = await resp.json(content_type=None)
    except Exception as err:
        _LOGGER.debug("Failed Nominatim reverse geocode for %s,%s: %s", lat, lng, err)
        return None, None

    if not isinstance(payload, dict):
        return None, None
    address = payload.get("address", {})
    commune = (
        address.get("city") or address.get("town") or address.get("village")
        or address.get("municipality") or address.get("county")
    )
    dept = _department_code_from_postcode(address.get("postcode"))
    return commune, dept


async def reverse_geocode_commune(session, lat, lng):
    """Retrouve la commune française la plus proche d'un point (BAN puis Nominatim en repli)."""
    if session is None or lat is None or lng is None:
        return None, None

    payload = await _ban_reverse_request(session, lat, lng, geocode_type="municipality")
    if not payload or not payload.get("features"):
        payload = await _ban_reverse_request(session, lat, lng)

    features = payload.get("features") if isinstance(payload, dict) else None
    if features:
        props = features[0].get("properties", {})
        commune = props.get("city") or props.get("label")
        context = props.get("context", "")
        dept_raw = context.split(",")[0].strip() if context else None
        dept = normalize_department(dept_raw)
        if commune:
            return commune, dept

    return await _nominatim_reverse_request(session, lat, lng)


def normalize_recent_signalement(item):
    if not isinstance(item, dict):
        return None

    position = item.get("position") if isinstance(item.get("position"), dict) else {}
    latitude = _float(
        item.get("latitude") or item.get("lat") or item.get("y") or position.get("lat")
    )
    longitude = _float(
        item.get("longitude") or item.get("lng") or item.get("lon") or item.get("x")
        or position.get("lng") or position.get("lon")
    )
    if latitude is None or longitude is None:
        return None

    raw_url = item.get("url") or item.get("link")
    raw_id = str(item.get("id") or item.get("slug") or raw_url or item.get("title") or f"{latitude},{longitude}")

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "id": f"early-{raw_id}",
            "statut": PROBABLE_STATUTS[0],
            "etat": None,
            "url": raw_url,
        },
    }


async def fetch_recent_signalements(session, base_url, per_page):
    if session is None:
        return []
    url = f"{base_url}?per={max(1, min(per_page, 100))}"
    try:
        async with session.get(
            url, headers={"Accept": "application/json", "User-Agent": HTTP_USER_AGENT}, timeout=15
        ) as resp:
            if resp.status >= 400:
                _LOGGER.debug("signalements/recent returned HTTP %s", resp.status)
                return []
            payload = await resp.json(content_type=None)
    except Exception as err:
        _LOGGER.debug("Failed to fetch signalements/recent: %s", err)
        return []

    if not isinstance(payload, dict):
        return []
    items = payload.get("signalements") or payload.get("feux") or payload.get("data") or []
    if not isinstance(items, list):
        return []

    features = []
    for item in items:
        feature = normalize_recent_signalement(item)
        if feature is not None:
            features.append(feature)
    return features


async def async_fetch_json(session, url, timeout=15, retries=3):
    """Récupère un JSON via aiohttp, avec réessais espacés en cas d'échec transitoire (5xx).

    Utilise la même session aiohttp partagée que le reste de l'intégration (fetch_fire_details,
    fetch_recent_signalements), qui n'a jamais déclenché de blocage anti-bot côté
    feuxdeforet.fr. Remplace l'ancien sync_fetch_json basé sur `requests`, dont l'empreinte
    TLS/réseau différente déclenchait des HTTP 403 intermittents.
    """
    if session is None:
        return None
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            async with session.get(
                url,
                headers={
                    "User-Agent": HTTP_USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "fr-FR,fr;q=0.9",
                    "Referer": "https://feuxdeforet.fr/",
                },
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "async_fetch_json returned HTTP %s for %s (essai %d/%d)",
                        resp.status, url, attempt, retries,
                    )
                    last_error = f"HTTP {resp.status}"
                    if attempt < retries:
                        await asyncio.sleep(2 * attempt)
                    continue
                return await resp.json(content_type=None)
        except Exception as err:
            _LOGGER.debug(
                "async_fetch_json failed for %s (essai %d/%d): %s",
                url, attempt, retries, err,
            )
            last_error = err
            if attempt < retries:
                await asyncio.sleep(2 * attempt)
    _LOGGER.debug("async_fetch_json : échec définitif pour %s (%s)", url, last_error)
    return None


async def fetch_fire_details(session, url):
    """Récupère les détails d'un feu, avec un réessai si l'API répond 500/502/503.

    Retourne un tuple (details, status_code). status_code vaut None en cas d'exception réseau
    (timeout, DNS, etc.), ce qui permet à l'appelant de distinguer un 404 définitif (page
    supprimée, à ne plus jamais retenter) d'un échec transitoire (à retenter plus tard).
    """
    empty = {"date": None, "commune": None, "dept": None, "statut_detail": None}
    path = relative_path_from_url(url)
    if not path or session is None:
        return empty, None

    request_url = f"{RESOLVE_URL}?path={quote(path, safe='')}&page=1"
    payload = None
    status_code = None
    for attempt in range(2):
        try:
            async with session.get(
                request_url, headers={"User-Agent": HTTP_USER_AGENT}, timeout=10
            ) as resp:
                status_code = resp.status
                if resp.status in (500, 502, 503) and attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                if resp.status != 200:
                    _LOGGER.debug("resolve endpoint returned %s for %s", resp.status, path)
                    return empty, status_code
                payload = await resp.json(content_type=None)
                break
        except Exception as err:
            _LOGGER.debug("Failed to fetch fire details for %s: %s", path, err)
            return empty, None
    else:
        return empty, status_code

    if payload is None:
        return empty, status_code

    data = payload.get("data", {})
    date_str = data.get("date")
    signal_dt = None
    if date_str:
        try:
            signal_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            signal_dt = None

    dept = normalize_department(data.get("dept"), url=url)

    return {
        "date": signal_dt,
        "commune": data.get("commune") or None,
        "dept": dept,
        "statut_detail": data.get("headlineEtat") or None,
    }, status_code


def elapsed_since(dt):
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    delta = now - dt
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 0:
        return "à l'instant"
    if total_minutes < 60:
        return f"{total_minutes} min"
    total_hours = total_minutes // 60
    if total_hours < 24:
        remaining_minutes = total_minutes % 60
        if remaining_minutes:
            return f"{total_hours} h {remaining_minutes} min"
        return f"{total_hours} h"
    days = total_hours // 24
    remaining_hours = total_hours % 24
    if remaining_hours:
        return f"{days} j {remaining_hours} h"
    return f"{days} j"