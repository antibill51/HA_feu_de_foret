"""The Feux de forêt integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .const import (
    CONF_DEBUG_LOGGING,
    CONF_ENABLE_PERSISTENT_NOTIFICATIONS,
    CONF_ENABLE_TELEGRAM_NOTIFICATIONS,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_NOTIFICATION_MAX_DISTANCE_KM,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    CONF_TELEGRAM_NOTIFY_SERVICE,
    DEFAULT_DEBUG_LOGGING,
    DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS,
    DEFAULT_ENABLE_TELEGRAM_NOTIFICATIONS,
    DEFAULT_NAME,
    DEFAULT_NOTIFICATION_MAX_DISTANCE_KM,
    DEFAULT_RADIUS_KM,
    DEFAULT_RECENT_PER_PAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TELEGRAM_NOTIFY_SERVICE,
    DOMAIN,
    ETAT_LABELS,
    GEOJSON_URL,
    ONGOING_ETATS,
    ONGOING_STATUTS,
    PROBABLE_STATUTS,
    RECENT_SIGNALEMENTS_URL,
    STATUT_EARLY_LABEL,
    STATUT_PROBABLE_LABEL,
)
from .utils import (
    async_fetch_json,
    extract_point_from_feature,
    fetch_recent_signalements,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["geo_location", "sensor", "binary_sensor"]
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}/fire_detection_dates"
SETUP_LOCK_KEY = f"{DOMAIN}_setup_in_progress"


def _is_confirmed(props):
    return props.get("statut") in ONGOING_STATUTS and props.get("etat") in ONGOING_ETATS


def _is_pending(props):
    return props.get("statut") in PROBABLE_STATUTS


def _zone_name(entry):
    return entry.options.get(CONF_NAME, entry.data.get(CONF_NAME, DEFAULT_NAME))


def _title_for(entry, radius):
    return f"{_zone_name(entry)} ({radius} km)"


def _apply_debug_logging(entry: ConfigEntry) -> None:
    debug_enabled = entry.options.get(CONF_DEBUG_LOGGING, entry.data.get(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING))
    level = logging.DEBUG if debug_enabled else logging.NOTSET
    logging.getLogger("custom_components.feux_de_foret").setLevel(level)
    if debug_enabled:
        _LOGGER.debug("Mode debug activé pour l'entrée %s", entry.entry_id)


def _serialize_detection_dates(detection_dates):
    return {fire_id: dt.isoformat() for fire_id, dt in (detection_dates or {}).items() if dt is not None}


async def _async_load_detection_dates(store):
    data = await store.async_load() or {}
    loaded = {}
    for fire_id, value in data.items():
        if not value:
            continue
        if isinstance(value, str):
            parsed = dt_util.parse_datetime(value)
            if parsed is not None:
                loaded[fire_id] = parsed
        elif hasattr(value, "isoformat"):
            loaded[fire_id] = value
    return loaded


async def _seed_detection_dates(coordinator, features):
    if not hasattr(coordinator, "fire_detection_dates"):
        coordinator.fire_detection_dates = {}
    now = dt_util.utcnow()
    changed = False
    for feature in features or []:
        props = feature.get("properties", {})
        if not (_is_confirmed(props) or _is_pending(props)):
            continue
        fire_id = str(props.get("id"))
        if fire_id not in coordinator.fire_detection_dates:
            coordinator.fire_detection_dates[fire_id] = now
            changed = True
    if changed and hasattr(coordinator, "_detection_store"):
        await coordinator._detection_store.async_save(_serialize_detection_dates(coordinator.fire_detection_dates))


def _merge_early_features(main_features, early_features):
    if not early_features:
        return main_features

    known_urls = set()
    for feature in main_features:
        url = feature.get("properties", {}).get("url")
        if url:
            known_urls.add(url)

    merged = list(main_features)
    for feature in early_features:
        props = feature.get("properties", {})
        url = props.get("url")
        if url and url in known_urls:
            continue
        merged.append(feature)

    return merged


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(SETUP_LOCK_KEY, set())
    if entry.entry_id in hass.data[SETUP_LOCK_KEY]:
        _LOGGER.warning(
            "Setup déjà en cours pour l'entrée %s, appel ignoré (double déclenchement détecté)",
            entry.entry_id,
        )
        return True
    hass.data[SETUP_LOCK_KEY].add(entry.entry_id)

    try:
        _apply_debug_logging(entry)

        current_radius = entry.options.get(CONF_RADIUS, entry.data.get(CONF_RADIUS, DEFAULT_RADIUS_KM))
        expected_title = _title_for(entry, current_radius)
        if entry.title != expected_title:
            hass.config_entries.async_update_entry(entry, title=expected_title)

        scan_minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        async def _async_update_data():
            session = async_get_clientsession(hass)
            payload = await async_fetch_json(session, GEOJSON_URL, 15)
            if not payload:
                raise UpdateFailed("Erreur de connexion à feuxdeforet.fr : aucune donnée reçue")

            features = payload.get("data", {}).get("features", [])
            _LOGGER.debug("GeoJSON principal : %d features reçues", len(features))

            early_features = await fetch_recent_signalements(session, RECENT_SIGNALEMENTS_URL, DEFAULT_RECENT_PER_PAGE)
            _LOGGER.debug("Signalements récents (anticipés) : %d reçus", len(early_features))

            features = _merge_early_features(features, early_features)
            _LOGGER.debug("Total après fusion : %d features", len(features))

            await _seed_detection_dates(coordinator, features)

            coordinator.last_fetch_success = dt_util.utcnow()
            await _async_notify_new_fires(hass, entry, coordinator, features)
            return features

        coordinator = DataUpdateCoordinator(
            hass, _LOGGER, name=f"{DOMAIN}_{entry.entry_id}",
            update_method=_async_update_data, update_interval=timedelta(minutes=scan_minutes),
        )
        coordinator.last_fetch_success = None
        coordinator.fire_details = {}
        coordinator.commune_cache = {}
        coordinator.notified_fire_ids = set()
        coordinator._detection_store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}/{entry.entry_id}")
        coordinator.fire_detection_dates = await _async_load_detection_dates(coordinator._detection_store)

        await coordinator.async_config_entry_first_refresh()

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = coordinator

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        return True
    finally:
        hass.data[SETUP_LOCK_KEY].discard(entry.entry_id)


async def _async_notify_new_fires(hass, entry, coordinator, features):
    persistent_enabled = entry.options.get(CONF_ENABLE_PERSISTENT_NOTIFICATIONS, DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS)
    telegram_enabled = entry.options.get(CONF_ENABLE_TELEGRAM_NOTIFICATIONS, DEFAULT_ENABLE_TELEGRAM_NOTIFICATIONS)
    if not persistent_enabled and not telegram_enabled:
        return

    home_lat = entry.data.get(CONF_LATITUDE)
    home_lng = entry.data.get(CONF_LONGITUDE)
    radius_km = entry.options.get(CONF_RADIUS, entry.data.get(CONF_RADIUS, DEFAULT_RADIUS_KM))
    max_distance = entry.options.get(CONF_NOTIFICATION_MAX_DISTANCE_KM, DEFAULT_NOTIFICATION_MAX_DISTANCE_KM)
    threshold_km = max_distance if max_distance and max_distance > 0 else radius_km

    from .utils import (
        commune_from_url,
        commune_with_department,
        department_from_url,
        full_url,
    )

    for feature in features:
        props = feature.get("properties", {})
        confirmed = _is_confirmed(props)
        pending = _is_pending(props)
        if not confirmed and not pending:
            continue

        fire_id = str(props.get("id"))
        if fire_id in coordinator.notified_fire_ids:
            continue

        lat, lng = extract_point_from_feature(feature)
        if lat is None or lng is None:
            continue
        dist_m = distance(home_lat, home_lng, lat, lng)
        dist_km = dist_m / 1000 if dist_m is not None else None
        if dist_km is None or dist_km > threshold_km:
            continue

        coordinator.notified_fire_ids.add(fire_id)
        is_early = fire_id.startswith("early-")

        if pending:
            commune_label = coordinator.commune_cache.get(fire_id, {}).get("commune") or "Zone à confirmer"
            etat_label = STATUT_EARLY_LABEL if is_early else STATUT_PROBABLE_LABEL
            url = full_url(props.get("url")) if is_early else None
        else:
            details = coordinator.fire_details.get(fire_id, {})
            commune = details.get("commune") or commune_from_url(props.get("url"))
            dept = details.get("dept") or department_from_url(props.get("url"))
            commune_label = commune_with_department(commune, dept)
            etat_label = details.get("statut_detail") or ETAT_LABELS.get(props.get("etat"), props.get("etat"))
            url = full_url(props.get("url"))

        zone_name = _zone_name(entry)
        if is_early:
            prefix = "🕐 Signalement anticipé"
        elif pending:
            prefix = "⚠️ Signalement non confirmé"
        else:
            prefix = "🔥 Feu confirmé"
        message = f"{commune_label} — {etat_label} — {round(dist_km, 1)} km de {zone_name}."
        if url:
            message += f"\n{url}"

        _LOGGER.debug("Notification déclenchée pour %s (%s) : %s", fire_id, prefix, message)

        if persistent_enabled:
            persistent_notification.async_create(
                hass, message, title=f"{prefix} — {zone_name}",
                notification_id=f"{DOMAIN}_{entry.entry_id}_{fire_id}",
            )
        if telegram_enabled:
            await _async_send_telegram(hass, entry, coordinator, message, zone_name, pending, is_early)


async def _async_send_telegram(hass, entry, coordinator, message, zone_name, pending=False, is_early=False):
    target = str(entry.options.get(CONF_TELEGRAM_NOTIFY_SERVICE, DEFAULT_TELEGRAM_NOTIFY_SERVICE)).strip()
    if not target:
        return

    if is_early:
        prefix = "🕐 Signalement anticipé"
    elif pending:
        prefix = "⚠️ Signalement non confirmé"
    else:
        prefix = "🔥 Feu confirmé"
    full_message = f"{prefix} — {zone_name}\n\n{message}"
    legacy_service = target.removeprefix("notify.") if target.startswith("notify.") else target

    try:
        if hass.services.has_service("notify", legacy_service):
            await hass.services.async_call(
                "notify", legacy_service,
                {"title": f"{prefix} — {zone_name}", "message": full_message}, blocking=True,
            )
            coordinator.last_telegram_error = None
            return

        notify_entity = target if target.startswith("notify.") else f"notify.{target}"
        if hass.services.has_service("notify", "send_message") and hass.states.get(notify_entity):
            await hass.services.async_call(
                "notify", "send_message",
                {"entity_id": notify_entity, "message": full_message}, blocking=True,
            )
            coordinator.last_telegram_error = None
            return

        coordinator.last_telegram_error = (
            f"Cible notify '{target}' introuvable. Utilisez un service legacy "
            "comme 'telegram' ou une entité comme 'notify.telegram_bot_chat'."
        )
        _LOGGER.warning("Notification Telegram activée mais %s", coordinator.last_telegram_error)
    except Exception as err: # noqa: BLE001
        coordinator.last_telegram_error = str(err)
        _LOGGER.warning("Échec de la notification Telegram : %s", err)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _apply_debug_logging(entry)

    new_radius = entry.options.get(CONF_RADIUS, entry.data.get(CONF_RADIUS, DEFAULT_RADIUS_KM))
    new_title = _title_for(entry, new_radius)
    if entry.title != new_title:
        hass.config_entries.async_update_entry(entry, title=new_title)

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok