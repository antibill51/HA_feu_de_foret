"""Geolocation platform for Feux de forêt."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    DOMAIN,
    ETAT_LABELS,
    ONGOING_ETATS,
    ONGOING_STATUTS,
    PROBABLE_STATUTS,
    STATUT_EARLY_LABEL,
    STATUT_PROBABLE_LABEL,
)
from .entity import device_info_for
from .utils import (
    commune_from_url,
    commune_with_department,
    department_from_url,
    elapsed_since,
    extract_point_from_feature,
    fetch_fire_details,
    full_url,
    reverse_geocode_commune,
)

FIRE_ICON_DATA_URI = (
    "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgd2lkdGg9IjMyIiBoZWlnaHQ9IjMyIj4KPHBhdGggZmlsbD0iI2QzMmYyZiIgZD0iTTE3LjY2IDExLjJjLS4yMy0uMy0uNTEtLjU2LS43Ny0uODItLjY3LS42LTEuNDMtMS4wMy0yLjA3LTEuNjZDMTMuMzMgNy4yNiAxMyA0Ljg1IDEzLjk1IDNjLS45NS4yMy0xLjc4Ljc1LTIuNDkgMS4zMi0yLjU5IDIuMDgtMy42MSA1Ljc1LTIuMzkgOC45LjA0LjEuMDguMi4wOC4zMyAwIC4yMi0uMTUuNDItLjM1LjUtLjIzLjEtLjQ3LjA0LS42Ni0uMTJhLjU4LjU4IDAgMCAxLS4xNC0uMTdjLTEuMTMtMS40My0xLjMxLTMuNDgtLjU1LTUuMTJDNS43OCAxMCA0Ljg3IDEzLjc1IDYuMDkgMTYuODVjLjM0Ljg1Ljc1IDEuNzEgMS40MiAyLjQuMi4yMS40LjQuNjUuNTUuOS42IDEuOTguOTQgMy4wNiAxLjA2MS41LjE1IDMuMDUtLjA1IDQuNDYtLjYgMy4yNC0xLjI4IDUuMDYtNC41IDQuNjItOC4wMi0uMTUtMS4wOC0uNi0yLjA5LTEuMjUtMi45OVoiLz4KPC9zdmc+"
)

FIRE_PENDING_ICON_DATA_URI = (
    "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgd2lkdGg9IjMyIiBoZWlnaHQ9IjMyIj4KPHBhdGggZmlsbD0ibm9uZSIgc3Ryb2tlPSIjZjVhNjIzIiBzdHJva2Utd2lkdGg9IjEuNiIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLWRhc2hhcnJheT0iMi4yLDEuNiIgZD0iTTE3LjY2IDExLjJjLS4yMy0uMy0uNTEtLjU2LS43Ny0uODItLjY3LS42LTEuNDMtMS4wMy0yLjA3LTEuNjZDMTMuMzMgNy4yNiAxMyA0Ljg1IDEzLjk1IDNjLS45NS4yMy0xLjc4Ljc1LTIuNDkgMS4zMi0yLjU5IDIuMDgtMy42MSA1Ljc1LTIuMzkgOC45LjA0LjEuMDguMi4wOC4zMyAwIC4yMi0uMTUuNDItLjM1LjUtLjIzLjEtLjQ3LjA0LS42Ni0uMTJhLjU4LjU4IDAgMCAxLS4xNC0uMTdjLTEuMTMtMS40My0xLjMxLTMuNDgtLjU1LTUuMTJDNS43OCAxMCA0Ljg3IDEzLjc1IDYuMDkgMTYuODVjLjM0Ljg1Ljc1IDEuNzEgMS40MiAyLjQuMi4yMS40LjQuNjUuNTUuOS42IDEuOTguOTQgMy4wNiAxLjA2MS41LjE1IDMuMDUtLjA1IDQuNDYtLjYgMy4yNC0xLjI4IDUuMDYtNC41IDQuNjItOC4wMi0uMTUtMS4wOC0uNi0yLjA5LTEuMjUtMi45OVoiLz4KPC9zdmc+"
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=5)

# Nombre max d'appels réseau (resolve / géocodage inverse) menés en parallèle. Un lot trop
# grand risque de saturer feuxdeforet.fr (déjà instable, cf. 500/502/503 fréquents) ; un lot
# trop petit ramène au comportement séquentiel lent d'origine. 5 est un compromis raisonnable.
_CONCURRENCY_LIMIT = 5


def _is_confirmed(props):
    return props.get("statut") in ONGOING_STATUTS and props.get("etat") in ONGOING_ETATS


def _is_pending(props):
    return props.get("statut") in PROBABLE_STATUTS


def _is_early(props):
    return str(props.get("id", "")).startswith("early-")


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    manager = FeuxDeForetManager(hass, coordinator, entry, async_add_entities)
    # Fire-and-forget : ne bloque pas le démarrage de Home Assistant en attendant que tous les
    # feux (potentiellement 50+) aient chacun leur appel resolve/géocodage résolu.
    hass.async_create_task(manager.async_update())
    coordinator.async_add_listener(manager.async_update_callback)


class FeuxDeForetManager:
    """Crée et met à jour une entité geo_location par feu, confirmé ou en attente, partout en France."""

    def __init__(self, hass, coordinator, entry, async_add_entities):
        self._hass = hass
        self._coordinator = coordinator
        self._entry = entry
        self._async_add_entities = async_add_entities
        self._entities = {}
        self._update_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(_CONCURRENCY_LIMIT)
        if not hasattr(coordinator, "fire_details"):
            coordinator.fire_details = {}
        self._details_cache = coordinator.fire_details
        if not hasattr(coordinator, "commune_cache"):
            coordinator.commune_cache = {}
        self._commune_cache = coordinator.commune_cache
        if not hasattr(coordinator, "fire_permanent_failures"):
            coordinator.fire_permanent_failures = set()
        self._permanent_failures = coordinator.fire_permanent_failures

    @property
    def _home_lat(self):
        return self._entry.data.get(CONF_LATITUDE)

    @property
    def _home_lng(self):
        return self._entry.data.get(CONF_LONGITUDE)

    @callback
    def async_update_callback(self):
        self._hass.async_create_task(self.async_update())

    async def _get_pending_commune(self, fire_id, lat, lng):
        """Trouve un nom de commune pour un point via géocodage inverse (BAN puis Nominatim)."""
        cached = self._commune_cache.get(fire_id)
        if cached is not None:
            return cached
        async with self._semaphore:
            session = async_get_clientsession(self._hass)
            commune, dept = await reverse_geocode_commune(session, lat, lng)
        result = {"commune": commune, "dept": dept}
        if commune is not None:
            self._commune_cache[fire_id] = result
        return result

    async def _get_details(self, fire_id, url, lat=None, lng=None):
        """Récupère les détails d'un feu confirmé, avec repli par géocodage inverse.

        Le repli s'applique dès que resolve ne fournit pas de commune exploitable — URL
        absente, 404 permanent déjà connu, ou échec transitoire (500/502/503/timeout). Comme
        cette résolution a lieu avant la création de l'entité (voir _async_update_locked), le
        nom affiché est déjà correct dès le premier cycle : plus d'entity_id figé sur
        "zone_inconnue" alors que le nom affiché se corrige ensuite silencieusement.
        """
        cached = self._details_cache.get(fire_id)
        if cached is not None:
            return cached
        empty = {"date": None, "commune": None, "dept": None, "statut_detail": None}

        details = empty
        if url and fire_id not in self._permanent_failures:
            async with self._semaphore:
                session = async_get_clientsession(self._hass)
                details, status_code = await fetch_fire_details(session, url)
            if details.get("date") is not None or details.get("commune") is not None:
                self._details_cache[fire_id] = details
                return details
            if status_code == 404:
                _LOGGER.debug("Feu %s : 404 définitif sur resolve, ne sera plus retenté", fire_id)
                self._permanent_failures.add(fire_id)

        if details.get("commune") is None and lat is not None and lng is not None:
            commune_info = await self._get_pending_commune(fire_id, lat, lng)
            if commune_info.get("commune") is not None:
                details = {**details, "commune": commune_info["commune"], "dept": commune_info.get("dept")}

        return details

    async def _resolve_details(self, fire_id, pending, url, lat, lng):
        if pending:
            return fire_id, await self._get_pending_commune(fire_id, lat, lng)
        return fire_id, await self._get_details(fire_id, url, lat, lng)

    async def async_update(self):
        async with self._update_lock:
            await self._async_update_locked()

    async def _async_update_locked(self):
        features = self._coordinator.data or []
        current_ids = set()
        new_entities = []

        candidates = []
        for feature in features:
            props = feature.get("properties", {})
            confirmed = _is_confirmed(props)
            pending = _is_pending(props)
            if not confirmed and not pending:
                continue

            lat, lng = extract_point_from_feature(feature)
            if lat is None or lng is None:
                _LOGGER.debug(
                    "Signalement %s sans coordonnées exploitables, ignoré — geometry=%s properties=%s",
                    props.get("id"), feature.get("geometry"), props,
                )
                continue

            fire_id = str(props.get("id"))
            candidates.append((fire_id, feature, props, pending, lat, lng))

        # Les appels réseau (resolve / géocodage inverse) sont lancés en parallèle, avec un
        # plafond de concurrence (_CONCURRENCY_LIMIT), et résolus intégralement AVANT la
        # création des entités ci-dessous. Ainsi, une entité n'est jamais créée avec un nom
        # provisoire "Zone inconnue" qui resterait figé dans son entity_id.
        results = await asyncio.gather(
            *(
                self._resolve_details(fire_id, pending, props.get("url"), lat, lng)
                for fire_id, feature, props, pending, lat, lng in candidates
            ),
            return_exceptions=True,
        )
        details_by_id = {}
        for (fire_id, *_rest), result in zip(candidates, results):
            if isinstance(result, Exception):
                _LOGGER.debug("Échec de résolution des détails pour %s : %s", fire_id, result)
                details_by_id[fire_id] = {
                    "date": None, "commune": None, "dept": None, "statut_detail": None,
                }
                continue
            _, details = result
            details_by_id[fire_id] = details

        detection_dates = getattr(self._coordinator, "fire_detection_dates", {})

        for fire_id, feature, props, pending, lat, lng in candidates:
            dist_m = distance(self._home_lat, self._home_lng, lat, lng)
            dist_km = dist_m / 1000 if dist_m is not None else None
            details = details_by_id.get(fire_id, {})

            if details.get("date") is None:
                detected_at = detection_dates.get(fire_id)
                if detected_at is None:
                    detected_at = dt_util.utcnow()
                    detection_dates[fire_id] = detected_at
                details = dict(details)
                details["date"] = detected_at

            current_ids.add(fire_id)

            if fire_id in self._entities:
                self._entities[fire_id].update_from_feature(feature, dist_km, details)
            else:
                entity = FeuDeForetLocationEvent(self._entry, fire_id, feature, dist_km, details)
                self._entities[fire_id] = entity
                new_entities.append(entity)

        stale_ids = set(self._entities.keys()) - current_ids
        if stale_ids:
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(self._hass)
            for stale_id in stale_ids:
                entity = self._entities.pop(stale_id)
                self._details_cache.pop(stale_id, None)
                self._commune_cache.pop(stale_id, None)
                self._permanent_failures.discard(stale_id)
                if entity.entity_id and registry.async_get(entity.entity_id):
                    registry.async_remove(entity.entity_id)
                else:
                    await entity.async_remove(force_remove=True)

        if new_entities:
            self._async_add_entities(new_entities)


class FeuDeForetLocationEvent(GeolocationEvent):
    """Une entité par feu. L'icône passe automatiquement de 'en attente' à 'confirmé' dès que le statut change."""

    _attr_should_poll = False
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, entry, fire_id, feature, dist_km, details):
        self._entry = entry
        self._fire_id = fire_id
        self._latitude = None
        self._longitude = None
        self._attr_unique_id = f"{entry.entry_id}_fire_{fire_id}"
        self._attr_device_info = device_info_for(entry)
        self._update_state(feature, dist_km, details)

    def _update_state(self, feature, dist_km, details):
        props = feature.get("properties", {})
        lat, lng = extract_point_from_feature(feature)
        if lat is not None and lng is not None:
            self._latitude = lat
            self._longitude = lng
        self._statut = props.get("statut")
        self._is_early = _is_early(props)
        is_pending = self._statut in PROBABLE_STATUTS
        self._confirmed = not is_pending

        if is_pending:
            commune = details.get("commune") or commune_from_url(props.get("url"))
            dept = details.get("dept") or department_from_url(props.get("url"))
            self._commune = commune
            self._dept = dept
            self._commune_label = commune_with_department(commune, dept)
            self._etat = None
            self._statut_detail = STATUT_EARLY_LABEL if self._is_early else STATUT_PROBABLE_LABEL
            self._url = full_url(props.get("url")) if self._is_early else None
            self._signal_dt = details.get("date")
            self._attr_icon = "mdi:fire-alert"
        else:
            commune = details.get("commune") or commune_from_url(props.get("url"))
            dept = details.get("dept") or department_from_url(props.get("url"))
            self._commune = commune
            self._dept = dept
            self._commune_label = commune_with_department(commune, dept)
            self._etat = props.get("etat")
            self._statut_detail = details.get("statut_detail")
            self._url = full_url(props.get("url"))
            self._signal_dt = details.get("date")
            self._attr_icon = "mdi:fire"

        self._distance_km = round(dist_km, 1) if dist_km is not None else None
        self._elapsed = elapsed_since(self._signal_dt)
        self._attr_name = self._commune_label

    def update_from_feature(self, feature, dist_km, details):
        was_confirmed = self._confirmed
        self._update_state(feature, dist_km, details)
        if not was_confirmed and self._confirmed:
            _LOGGER.info("Signalement %s confirmé — passage en feu confirmé (%s)", self._fire_id, self._commune_label)
        self.async_write_ha_state()

    @property
    def source(self):
        return DOMAIN

    @property
    def entity_picture(self):
        if not self._confirmed:
            return FIRE_PENDING_ICON_DATA_URI
        return FIRE_ICON_DATA_URI

    @property
    def latitude(self):
        return self._latitude

    @property
    def longitude(self):
        return self._longitude

    @property
    def distance(self):
        return self._distance_km

    @property
    def extra_state_attributes(self):
        attrs = {
            "commune": self._commune, "departement": self._dept,
            "commune_departement": self._commune_label, "statut": self._statut,
            "confirme": self._confirmed, "anticipe": self._is_early,
            "etat": self._etat,
            "etat_label": ETAT_LABELS.get(self._etat, self._etat) if self._etat else self._statut_detail,
            "url": self._url, "id": self._fire_id,
        }
        if self._statut_detail:
            attrs["statut_detail"] = self._statut_detail
        attrs["signale_le"] = self._signal_dt.isoformat() if self._signal_dt is not None else "9999-12-31T23:59:59+00:00"
        attrs["signale_depuis"] = self._elapsed if self._elapsed is not None else "date inconnue"
        return attrs