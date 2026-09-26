"""Helper utilities for Feux de forêt integration."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

from .const import (
    BAN_REVERSE_URL,
    BAN_SEARCH_URL,
    BASE_URL,
    ETAT_LABELS,
    HTTP_USER_AGENT,
    NOMINATIM_SEARCH_URL,
    PROBABLE_STATUTS,
    RESOLVE_URL,
    STATUT_EARLY_LABEL,
    STATUT_PROBABLE_LABEL,
)

_LOGGER = logging.getLogger(__name__)

# Cache mémoire pour éviter les requêtes répétées de géocodage par commune
_COMMUNE_COORDS_CACHE: dict[str, tuple[float, float] | None] = {}

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

# Champ de dernière mise à jour du statut renvoyé par l'endpoint resolve.
_UPDATE_TIMESTAMP_KEY = "updatedAt"

# Mapping des départements français (nom normalisé -> numéro de département).
DEPARTEMENTS = {
    "ain": "01", "aisne": "02", "allier": "03", "alpes-de-haute-provence": "04",
    "hautes-alpes": "05", "alpes-maritimes": "06", "ardeche": "07", "ardennes": "08",
    "ariege": "09", "aube": "10", "aude": "11", "aveyron": "12",
    "bouches-du-rhone": "13", "calvados": "14", "cantal": "15", "charente": "16",
    "charente-maritime": "17", "cher": "18", "correze": "19", "corse-du-sud": "2A",
    "haute-corse": "2B", "cote-d-or": "21", "cotes-d-armor": "22", "creuse": "23",
    "dordogne": "24", "doubs": "25", "drome": "26", "eure": "27",
    "eure-et-loir": "28", "finistere": "29", "gard": "30", "haute-garonne": "31",
    "gers": "32", "gironde": "33", "herault": "34", "ille-et-vilaine": "35",
    "indre": "36", "indre-et-loire": "37", "isere": "38", "jura": "39",
    "landes": "40", "loir-et-cher": "41", "loire": "42", "haute-loire": "43",
    "loire-atlantique": "44", "loiret": "45", "lot": "46", "lot-et-garonne": "47",
    "lozere": "48", "maine-et-loire": "49", "manche": "50", "marne": "51",
    "haute-marne": "52", "mayenne": "53", "meurthe-et-moselle": "54", "meuse": "55",
    "morbihan": "56", "moselle": "57", "nievre": "58", "nord": "59",
    "oise": "60", "orne": "61", "pas-de-calais": "62", "puy-de-dome": "63",
    "pyrenees-atlantiques": "64", "hautes-pyrenees": "65", "pyrenees-orientales": "66",
    "bas-rhin": "67", "haut-rhin": "68", "rhone": "69", "haute-saone": "70",
    "saone-et-loire": "71", "sarthe": "72", "savoie": "73", "haute-savoie": "74",
    "paris": "75", "seine-maritime": "76", "seine-et-marne": "77", "yvelines": "78",
    "deux-sevres": "79", "somme": "80", "tarn": "81", "tarn-et-garonne": "82",
    "var": "83", "vaucluse": "84", "vendee": "85", "vienne": "86",
    "haute-vienne": "87", "vosges": "88", "yonne": "89", "territoire-de-belfort": "90",
    "essonne": "91", "hauts-de-seine": "92", "seine-saint-denis": "93",
    "val-de-marne": "94", "val-d-oise": "95", "guadeloupe": "971", "martinique": "972",
    "guyane": "973", "la-reunion": "974", "mayotte": "976",
}


def _float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def extract_point(geometry):
    """Extrait (lat, lng) en float depuis un dict de géométrie GeoJSON standard."""
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


def _clean_slug(slug):
    slug = re.sub(r"-\d+$", "", slug)
    slug = re.sub(r"-\d{2}-\d{2}-\d{4}$", "", slug)
    return slug


def _format_name(slug):
    return " ".join(part.capitalize() for part in slug.split("-"))


def commune_from_url(url):
    """Extrait le nom lisible de la commune depuis une URL feuxdeforet.fr."""
    if not url:
        return None
    match = re.search(r"/[^/]+/([^/]+)/?$", url)
    if not match:
        return None
    slug = _clean_slug(match.group(1))
    return _format_name(slug)


def department_from_url(url):
    """Extrait le numéro du département (ex: '13', '2A') depuis une URL feuxdeforet.fr."""
    if not url:
        return None
    match = re.search(r"/([^/]+)/[^/]+/?$", url)
    if not match:
        return None
    segment = match.group(1)
    dept_match = re.search(r"-(\d{2,3}|2[ABab])$", segment)
    if dept_match:
        return dept_match.group(1).upper()
    return DEPARTEMENTS.get(segment.lower())


def normalize_department(dept_value, url=None):
    """Normalise une valeur de département (code numérique, nom, ou URL de repli)."""
    if dept_value is not None:
        val = str(dept_value).strip()
        if re.match(r"^(\d{2,3}|2[ABab])$", val):
            return val.upper()
        clean = re.sub(r"[^\w\s-]", "", val).lower().replace(" ", "-")
        if clean in DEPARTEMENTS:
            return DEPARTEMENTS[clean]
    return department_from_url(url) if url else None


def commune_with_department(commune, dept):
    """Formate 'Commune (Dept)' ou juste 'Commune' si le département est inconnu."""
    if not commune:
        return "Localisation inconnue"
    return f"{commune} ({dept})" if dept else commune


def relative_path_from_url(url):
    """Extrait le chemin relatif (/dept-XX/slug-feu-YYYY/) pour l'endpoint resolve."""
    if not url:
        return None
    url = url.strip()
    match = re.search(r"https?://[^/]+(/.*)", url)
    if match:
        path = match.group(1)
    else:
        path = url if url.startswith("/") else f"/{url}"
    return path if path.endswith("/") else f"{path}/"


def full_url(url):
    """Retourne une URL absolue feuxdeforet.fr."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    path = url if url.startswith("/") else f"/{url}"
    return f"{BASE_URL}{path}"


async def _ban_reverse_request(session, lat, lng):
    url = f"{BAN_REVERSE_URL}?lat={lat}&lon={lng}"
    try:
        async with session.get(url, headers={"User-Agent": HTTP_USER_AGENT}, timeout=5) as resp:
            if resp.status != 200:
                return None, None
            data = await resp.json(content_type=None)
            features = data.get("features", [])
            if not features:
                return None, None
            props = features[0].get("properties", {})
            commune = props.get("city") or props.get("name")
            postcode = str(props.get("postcode", ""))
            dept = None
            if len(postcode) >= 2:
                dept = postcode[:3] if postcode.startswith("97") else postcode[:2]
            return commune, dept
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("BAN reverse geocoding failed for (%s, %s): %s", lat, lng, err)
        return None, None


async def _nominatim_reverse_request(session, lat, lng):
    url = f"{NOMINATIM_REVERSE_URL}?lat={lat}&lon={lng}&format=jsonv2&accept-language=fr"
    try:
        async with session.get(url, headers={"User-Agent": HTTP_USER_AGENT}, timeout=5) as resp:
            if resp.status != 200:
                return None, None
            data = await resp.json(content_type=None)
            address = data.get("address", {})
            commune = (
                address.get("village")
                or address.get("town")
                or address.get("city")
                or address.get("municipality")
            )
            postcode = str(address.get("postcode", ""))
            dept = None
            if len(postcode) >= 2:
                dept = postcode[:3] if postcode.startswith("97") else postcode[:2]
            return commune, dept
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Nominatim reverse geocoding failed for (%s, %s): %s", lat, lng, err)
        return None, None


async def reverse_geocode_commune(session, lat, lng):
    """Détermine la commune et le département depuis les coordonnées via la BAN puis Nominatim."""
    if session is None or lat is None or lng is None:
        return None, None
    commune, dept = await _ban_reverse_request(session, lat, lng)
    if commune is not None:
        return commune, dept
    return await _nominatim_reverse_request(session, lat, lng)


def fire_id_from_url(url: str | None) -> str | None:
    """Extrait l'ID numérique canonique d'un feu depuis son URL si disponible."""
    if not url:
        return None
    match = re.search(r"-(\d+)/?$", str(url).strip())
    if match:
        return match.group(1)
    return None


async def geocode_commune(session, commune: str | None, dept: str | None = None) -> tuple[float, float] | None:
    """Géocode une commune (avec code département éventuel) via la BAN puis Nominatim."""
    if session is None or not commune:
        return None

    cache_key = f"{str(commune).strip().lower()}_{str(dept).strip().lower() if dept else ''}"
    if cache_key in _COMMUNE_COORDS_CACHE:
        return _COMMUNE_COORDS_CACHE[cache_key]

    query = f"{commune} {dept}".strip() if dept else str(commune).strip()
    ban_url = f"{BAN_SEARCH_URL}?q={quote(query)}&type=municipality&limit=1"
    try:
        async with session.get(
            ban_url, headers={"User-Agent": HTTP_USER_AGENT}, timeout=8
        ) as resp:
            if resp.status == 200:
                payload = await resp.json(content_type=None)
                if isinstance(payload, dict) and payload.get("features"):
                    coords = payload["features"][0].get("geometry", {}).get("coordinates")
                    if coords and len(coords) >= 2:
                        lon, lat = float(coords[0]), float(coords[1])
                        _COMMUNE_COORDS_CACHE[cache_key] = (lat, lon)
                        return lat, lon
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("BAN geocode search failed for %s: %s", query, err)

    nom_url = f"{NOMINATIM_SEARCH_URL}?q={quote(query)}, France&format=jsonv2&limit=1"
    try:
        async with session.get(
            nom_url, headers={"User-Agent": HTTP_USER_AGENT}, timeout=8
        ) as resp:
            if resp.status == 200:
                payload = await resp.json(content_type=None)
                if isinstance(payload, list) and payload:
                    lat_str = payload[0].get("lat")
                    lon_str = payload[0].get("lon")
                    if lat_str is not None and lon_str is not None:
                        lat, lon = float(lat_str), float(lon_str)
                        _COMMUNE_COORDS_CACHE[cache_key] = (lat, lon)
                        return lat, lon
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Nominatim geocode search failed for %s: %s", query, err)

    _COMMUNE_COORDS_CACHE[cache_key] = None
    return None


def normalize_recent_signalement(item):
    """Version synchrone minimale conservée pour compatibilité."""
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
    fire_id = fire_id_from_url(raw_url) or (str(item.get("id")) if item.get("id") else None)
    raw_id = str(fire_id or item.get("slug") or raw_url or item.get("title") or f"{latitude},{longitude}")

    title = (item.get("title") or "").strip()
    title_lower = title.lower()
    en_cours = item.get("enCours")

    if en_cours is False:
        if "fausse alerte" in title_lower:
            statut = "fausse_alerte"
            etat = "fausse_alerte"
            statut_detail = "Fausse alerte"
        elif "éteint" in title_lower or "eteint" in title_lower:
            statut = "valide_publie"
            etat = "eteint"
            statut_detail = "Éteint"
        else:
            statut = "valide_publie"
            etat = "eteint"
            statut_detail = "Feu clôturé"
    else:
        statut = PROBABLE_STATUTS[0]
        etat = None
        statut_detail = STATUT_EARLY_LABEL

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "id": f"early-{raw_id}",
            "statut": statut,
            "etat": etat,
            "statut_detail": statut_detail,
            "url": raw_url,
            "title": title,
            "early": True if en_cours is not False else False,
            "enCours": en_cours,
        },
    }


async def async_normalize_recent_signalement(session, item):
    """Normalise un signalement anticipé en feature GeoJSON avec géocodage de commune."""
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

    commune = item.get("commune") or item.get("city") or item.get("nom")
    dept = item.get("dept") or item.get("departement") or item.get("dept_code")
    raw_url = item.get("url") or item.get("link")

    # Si les coordonnées ne sont pas fournies directement, géocoder la commune
    if (latitude is None or longitude is None) and commune:
        coords = await geocode_commune(session, str(commune), str(dept) if dept else None)
        if coords:
            latitude, longitude = coords

    if latitude is None or longitude is None:
        return None

    fire_id = fire_id_from_url(raw_url) or (str(item.get("id")) if item.get("id") else None)
    raw_id = str(fire_id or item.get("slug") or raw_url or item.get("title") or f"{latitude},{longitude}")

    # Si on a l'ID canonique du feu (ex: 12461), on l'utilise pour une transition transparente
    feature_id = str(fire_id) if fire_id else f"early-{raw_id}"

    title = (item.get("title") or "").strip()
    title_lower = title.lower()
    en_cours = item.get("enCours")

    if en_cours is False:
        if "fausse alerte" in title_lower:
            statut = "fausse_alerte"
            etat = "fausse_alerte"
            statut_detail = "Fausse alerte"
        elif "éteint" in title_lower or "eteint" in title_lower:
            statut = "valide_publie"
            etat = "eteint"
            statut_detail = "Éteint"
        elif "maîtrisé" in title_lower or "maitrise" in title_lower:
            statut = "valide_publie"
            etat = "maitrise"
            statut_detail = "Maîtrisé"
        elif "fixé" in title_lower or "fixe" in title_lower:
            statut = "valide_publie"
            etat = "fixe"
            statut_detail = "Fixé"
        else:
            statut = "valide_publie"
            etat = "eteint"
            statut_detail = "Feu clôturé"
    else:
        statut = PROBABLE_STATUTS[0]
        etat = None
        statut_detail = STATUT_EARLY_LABEL

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "id": feature_id,
            "statut": statut,
            "etat": etat,
            "statut_detail": statut_detail,
            "url": raw_url,
            "commune": commune,
            "dept": dept,
            "title": title,
            "early": True if en_cours is not False else False,
            "enCours": en_cours,
        },
    }


async def fetch_recent_signalements(session, base_url, per_page):
    """Récupère les signalements récents / anticipés et les géolocalise."""
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
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Failed to fetch signalements/recent: %s", err)
        return []

    if not isinstance(payload, dict):
        return []
    items = payload.get("signalements") or payload.get("feux") or payload.get("data") or []
    if not isinstance(items, list):
        return []

    results = await asyncio.gather(
        *(async_normalize_recent_signalement(session, item) for item in items),
        return_exceptions=True,
    )
    features = []
    for res in results:
        if isinstance(res, dict) and res.get("type") == "Feature":
            features.append(res)
    return features


async def async_fetch_json(session, url, timeout=15, retries=3):
    """Récupère un JSON via aiohttp, avec réessais espacés en cas d'échec transitoire (5xx)."""
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
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "async_fetch_json failed for %s (essai %d/%d): %s",
                url, attempt, retries, err,
            )
            last_error = err
            if attempt < retries:
                await asyncio.sleep(2 * attempt)
    _LOGGER.debug("async_fetch_json : échec définitif pour %s (%s)", url, last_error)
    return None


def _parse_iso_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


async def fetch_fire_details(session, url, fire_id=None):
    """Récupère les détails d'un feu, avec un réessai si l'API répond 500/502/503.

    Retourne un tuple (details, status_code). status_code vaut None en cas d'exception réseau
    (timeout, DNS, etc.), ce qui permet à l'appelant de distinguer un 404 définitif (page
    supprimée, à ne plus jamais retenter) d'un échec transitoire (à retenter plus tard).
    """
    empty = {
        "date": None,
        "commune": None,
        "dept": None,
        "statut_detail": None,
        "updated_at": None,
        "excerpt": None,
        "statut": None,
        "etat": None,
    }
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
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed to fetch fire details for %s: %s", path, err)
            return empty, None
    else:
        return empty, status_code

    if payload is None:
        return empty, status_code

    data = payload.get("data", {})
    date_str = data.get("date")
    signal_dt = _parse_iso_datetime(date_str)
    dept = normalize_department(data.get("dept"), url=url)
    updated_at = _parse_iso_datetime(data.get(_UPDATE_TIMESTAMP_KEY))

    raw_statut = data.get("statut")
    raw_etat = data.get("etat_feu") or data.get("etat")
    headline_etat = data.get("headlineEtat")
    excerpt = data.get("excerpt")

    statut_detail = headline_etat
    if not statut_detail:
        if raw_statut == "fausse_alerte" or raw_etat == "fausse_alerte" or (excerpt and "fausse alerte" in str(excerpt).lower()):
            statut_detail = "Fausse alerte"
            raw_statut = "fausse_alerte"
            raw_etat = "fausse_alerte"
        elif raw_etat == "eteint" or raw_statut == "eteint" or data.get("enCours") is False:
            statut_detail = "Éteint"
            raw_etat = "eteint"

    return {
        "date": signal_dt,
        "commune": data.get("commune") or None,
        "dept": dept,
        "statut_detail": statut_detail,
        "updated_at": updated_at,
        "excerpt": excerpt,
        "statut": raw_statut,
        "etat": raw_etat,
    }, status_code


def elapsed_since(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
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
