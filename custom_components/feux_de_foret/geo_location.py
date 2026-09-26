"""Geolocation platform for Feux de forêt."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATUS_FLAP_GRACE_MINUTES,
    DEFAULT_STATUS_FLAP_GRACE_MINUTES,
    DOMAIN,
    ETAT_LABELS,
    EVENT_FIRE_STATUS_CHANGED,
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

# Icône noire pour distinguer un feu éteint d'un feu actif ou en attente.
FIRE_EXTINGUISHED_ICON_DATA_URI = (
    "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgd2lkdGg9IjMyIiBoZWlnaHQ9IjMyIj4KPHBhdGggZmlsbD0iIzAwMDAwMCIgZD0iTTE3LjY2IDExLjJjLS4yMy0uMy0uNTEtLjU2LS43Ny0uODItLjY3LS42LTEuNDMtMS4wMy0yLjA3LTEuNjZDMTMuMzMgNy4yNiAxMyA0Ljg1IDEzLjk1IDNjLS45NS4yMy0xLjc4Ljc1LTIuNDkgMS4zMi0yLjU5IDIuMDgtMy42MSA1Ljc1LTIuMzkgOC45LjA0LjEuMDguMi4wOC4zMyAwIC4yMi0uMTUuNDItLjM1LjUtLjIzLjEtLjQ3LjA0LS42Ni0uMTJhLjU4LjU4IDAgMCAxLS4xNC0uMTdjLTEuMTMtMS40My0xLjMxLTMuNDgtLjU1LTUuMTJDNS43OCAxMCA0Ljg3IDEzLjc1IDYuMDkgMTYuODVjLjM0Ljg1Ljc1IDEuNzEgMS40MiAyLjQuMi4yMS40LjQuNjUuNTUuOS42IDEuOTguOTQgMy4wNiAxLjA2MS41LjE1IDMuMDUtLjA1IDQuNDYtLjYgMy4yNC0xLjI4IDUuMDYtNC41IDQuNjItOC4wMi0uMTUtMS4wOC0uNi0yLjA5LTEuMjUtMi45OVoiLz4KPC9zdmc+"
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=5)

# Limite les appels réseau parallèles de résolution et de géocodage.
_CONCURRENCY_LIMIT = 5

# Stockage persistant des délais de grâce et du repli local de changement d'état.
_STORAGE_VERSION = 1
_LAST_SEEN_STORAGE_KEY_PREFIX = f"{DOMAIN}/fire_last_seen"
_LAST_STATE_CHANGE_STORAGE_KEY_PREFIX = f"{DOMAIN}/fire_last_state_change"


def _is_confirmed(props):
    return props.get("statut") in ONGOING_STATUTS and props.get("etat") in ONGOING_ETATS


def _is_pending(props):
    return props.get("statut") in PROBABLE_STATUTS


def _is_early(props):
    return (
        str(props.get("id", "")).startswith("early-")
        or bool(props.get("early"))
        or props.get("statut") in ("douteux", "probable")
        or bool(props.get("anticipe"))
    )


def _serialize_datetime_dict(values):
    return {fire_id: dt.isoformat() for fire_id, dt in (values or {}).items() if dt is not None}


async def _async_load_datetime_dict(store):
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


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    manager = FeuxDeForetManager(hass, coordinator, entry, async_add_entities)
    # Chargement des chronomètres persistés AVANT le premier cycle : indispensable pour que
    # la toute première purge après un redémarrage/reload dispose déjà des bons horodatages,
    # plutôt que de traiter tous les feux absents comme "jamais vus" et donc hors grâce.
    await manager.async_load_persisted_state()
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
        # Horodatage de la dernière fois où chaque feu a été vu confirmé/en attente dans le
        # flux. Sert uniquement à calculer la période de grâce avant purge — voir
        # _async_purge_orphaned_entities et _grace_period. Persisté sur disque.
        if not hasattr(coordinator, "fire_last_seen"):
            coordinator.fire_last_seen = {}
        self._last_seen = coordinator.fire_last_seen
        self._last_seen_store = Store(
            hass, _STORAGE_VERSION, f"{_LAST_SEEN_STORAGE_KEY_PREFIX}/{entry.entry_id}"
        )
        # Marque les feux dont le statut post-sortie de flux a déjà été rafraîchi une fois
        # avec succès (voir _refresh_orphan_status). Non persisté : au pire, un seul appel
        # réseau supplémentaire est retenté après redémarrage, sans conséquence fonctionnelle.
        if not hasattr(coordinator, "fire_orphan_refreshed"):
            coordinator.fire_orphan_refreshed = set()
        self._orphan_refreshed = coordinator.fire_orphan_refreshed
        # Repli LOCAL pour "changement d'état depuis" : n'est utilisé que si feuxdeforet.fr ne
        # fournit pas encore de champ de mise à jour reconnu côté serveur (voir
        # utils._extract_update_timestamp / _UPDATE_TIMESTAMP_KEYS). Dès que ce champ est
        # identifié et correctement extrait, la valeur serveur prime systématiquement — voir
        # FeuDeForetLocationEvent.extra_state_attributes. Persisté sur disque par cohérence,
        # mais son rôle est amené à diminuer une fois le bon champ serveur confirmé.
        if not hasattr(coordinator, "fire_last_state_change"):
            coordinator.fire_last_state_change = {}
        self._last_state_change = coordinator.fire_last_state_change
        self._last_state_change_store = Store(
            hass, _STORAGE_VERSION, f"{_LAST_STATE_CHANGE_STORAGE_KEY_PREFIX}/{entry.entry_id}"
        )

    @property
    def _home_lat(self):
        return self._entry.data.get(CONF_LATITUDE)

    @property
    def _home_lng(self):
        return self._entry.data.get(CONF_LONGITUDE)

    @property
    def _grace_period(self):
        """Période de grâce avant suppression réelle d'une entité geo_location dont le feu
        a disparu du flux confirmé/en attente. Réutilise CONF_STATUS_FLAP_GRACE_MINUTES,
        exposé dans le config flow (options de l'intégration) — un réglage distinct de
        CONF_UNAVAILABLE_GRACE_MINUTES, qui gère lui l'indisponibilité de l'API
        feuxdeforet.fr elle-même (coordinator, sensors, binary_sensor).
        """
        minutes = self._entry.options.get(
            CONF_STATUS_FLAP_GRACE_MINUTES,
            self._entry.data.get(CONF_STATUS_FLAP_GRACE_MINUTES, DEFAULT_STATUS_FLAP_GRACE_MINUTES),
        )
        return timedelta(minutes=minutes)

    async def async_load_persisted_state(self):
        """Recharge fire_last_seen et fire_last_state_change depuis le disque au démarrage
        de la plateforme. Doit être appelé avant le premier appel à async_update().
        """
        loaded_last_seen = await _async_load_datetime_dict(self._last_seen_store)
        for fire_id, dt in loaded_last_seen.items():
            self._last_seen.setdefault(fire_id, dt)

        loaded_last_change = await _async_load_datetime_dict(self._last_state_change_store)
        for fire_id, dt in loaded_last_change.items():
            self._last_state_change.setdefault(fire_id, dt)

    async def _async_save_persisted_state(self):
        await self._last_seen_store.async_save(_serialize_datetime_dict(self._last_seen))
        await self._last_state_change_store.async_save(_serialize_datetime_dict(self._last_state_change))

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
        """Récupère les métadonnées détaillées (statut, date de signalement, commune BAN).

        Le résultat est mis en cache par fire_id pour éviter de réinterroger
        l'endpoint resolve à chaque cycle de 5 minutes tant que le feu reste actif.
        Pour un signalement sans commune BAN, le géocodage inverse de repli est tenté une fois.
        """
        cached = self._details_cache.get(fire_id)
        if cached is not None:
            return cached
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

        details = empty
        if url and fire_id not in self._permanent_failures:
            async with self._semaphore:
                session = async_get_clientsession(self._hass)
                details, status_code = await fetch_fire_details(session, url, fire_id=fire_id)
            if details.get("date") is not None or details.get("commune") is not None or details.get("statut") is not None:
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

    async def _refresh_orphan_status(self, fire_id, url):
        """Récupère UNE FOIS le texte de statut (et sa date de mise à jour serveur si
        disponible) d'un feu qui vient de sortir du flux confirmé/en attente.
        """
        if not url or fire_id in self._permanent_failures:
            return None
        async with self._semaphore:
            session = async_get_clientsession(self._hass)
            details, status_code = await fetch_fire_details(session, url, fire_id=fire_id)
        if status_code == 404:
            _LOGGER.debug(
                "Feu %s (grâce) : 404 définitif sur resolve, ne sera plus retenté", fire_id
            )
            self._permanent_failures.add(fire_id)
            return None
        if details.get("statut_detail") is None and details.get("statut") is None and details.get("date") is None:
            return None
        return details

    async def _resolve_details(self, fire_id, pending, url, lat, lng, commune=None, dept=None):
        if pending:
            if commune:
                return fire_id, {"commune": commune, "dept": dept}
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
            fire_id = str(props.get("id"))
            is_closed = (
                props.get("enCours") is False
                or props.get("statut") in ("fausse_alerte", "eteint")
                or props.get("etat") in ("fausse_alerte", "eteint")
            )

            if not confirmed and not pending:
                if not (is_closed and fire_id in self._entities):
                    continue

            lat, lng = extract_point_from_feature(feature)
            if lat is None or lng is None:
                _LOGGER.debug(
                    "Signalement %s sans coordonnées exploitables, ignoré — geometry=%s properties=%s",
                    props.get("id"), feature.get("geometry"), props,
                )
                continue

            if fire_id in self._entities:
                prev_ent = self._entities[fire_id]
                if prev_ent._etat != props.get("etat") or prev_ent._statut != props.get("statut"):
                    self._details_cache.pop(fire_id, None)
            candidates.append((fire_id, feature, props, pending, lat, lng, is_closed))

        # Les appels réseau (resolve / géocodage inverse) sont lancés en parallèle, avec un
        # plafond de concurrence (_CONCURRENCY_LIMIT), et résolus intégralement AVANT la
        # création des entités ci-dessous.
        results = await asyncio.gather(
            *(
                self._resolve_details(
                    fire_id, pending, props.get("url"), lat, lng,
                    props.get("commune"), props.get("dept"),
                )
                for fire_id, feature, props, pending, lat, lng, is_closed in candidates
            ),
            return_exceptions=True,
        )
        details_by_id = {}
        for (fire_id, *_rest), result in zip(candidates, results):
            if isinstance(result, Exception):
                _LOGGER.debug("Échec de résolution des détails pour %s : %s", fire_id, result)
                details_by_id[fire_id] = {
                    "date": None, "commune": None, "dept": None, "statut_detail": None, "updated_at": None,
                }
                continue
            _, details = result
            details_by_id[fire_id] = details

        detection_dates = getattr(self._coordinator, "fire_detection_dates", {})
        now = dt_util.utcnow()

        for fire_id, feature, props, pending, lat, lng, is_closed in candidates:
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

            if not is_closed:
                current_ids.add(fire_id)
                self._last_seen[fire_id] = now
                self._orphan_refreshed.discard(fire_id)

            if fire_id in self._entities:
                self._entities[fire_id].update_from_feature(feature, dist_km, details)
            elif not is_closed:
                entity = FeuDeForetLocationEvent(
                    self._hass, self._entry, fire_id, feature, dist_km, details,
                    self._last_state_change,
                )
                self._entities[fire_id] = entity
                new_entities.append(entity)

        await self._async_purge_orphaned_entities(current_ids)
        await self._async_save_persisted_state()

        if new_entities:
            self._async_add_entities(new_entities)

    async def _async_purge_orphaned_entities(self, current_ids):
        """Supprime du registre toute entité geo_location de cette entrée dont le feu
        n'est plus présent dans le flux actuel depuis plus longtemps que _grace_period.
        """
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self._hass)
        prefix = f"{self._entry.entry_id}_fire_"
        orphaned = 0
        grace_protected = 0
        grace_period = self._grace_period
        now = dt_util.utcnow()

        orphan_entries = []
        for entity_entry in er.async_entries_for_config_entry(registry, self._entry.entry_id):
            if entity_entry.domain != "geo_location":
                continue
            if not entity_entry.unique_id.startswith(prefix):
                continue
            fire_id = entity_entry.unique_id[len(prefix):]
            if fire_id in current_ids:
                continue
            orphan_entries.append((entity_entry, fire_id))

        to_refresh = []
        to_purge = []
        for entity_entry, fire_id in orphan_entries:
            # Si l'entité n'est pas instanciée en mémoire (ex: restaurée après un redémarrage
            # mais le feu était déjà clôturé/absent du flux), on la purge immédiatement pour
            # ne jamais laisser d'entité zombie 'unavailable' dans Home Assistant.
            entity = self._entities.get(fire_id)
            if entity is None:
                to_purge.append((entity_entry, fire_id))
                continue

            last_seen = self._last_seen.get(fire_id)
            if last_seen is not None and (now - last_seen) < grace_period:
                grace_protected += 1
                if fire_id not in self._orphan_refreshed and entity.status_source_url:
                    to_refresh.append((fire_id, entity.status_source_url))
                continue
            to_purge.append((entity_entry, fire_id))

        if to_refresh:
            refresh_results = await asyncio.gather(
                *(self._refresh_orphan_status(fire_id, url) for fire_id, url in to_refresh),
                return_exceptions=True,
            )
            for (fire_id, _url), result in zip(to_refresh, refresh_results):
                if isinstance(result, Exception):
                    _LOGGER.debug(
                        "Échec du rafraîchissement de statut (grâce) pour %s : %s — nouvel "
                        "essai au prochain cycle", fire_id, result,
                    )
                    continue
                if result is None:
                    continue
                entity = self._entities.get(fire_id)
                if entity is not None:
                    entity.apply_status_refresh(result)
                self._orphan_refreshed.add(fire_id)

        detection_dates = getattr(self._coordinator, "fire_detection_dates", {})
        notified_ids = getattr(self._coordinator, "notified_fire_ids", set())
        detection_dates_changed = False

        for entity_entry, fire_id in to_purge:
            _LOGGER.debug(
                "Feu %s absent du flux (orphelin/clôturé) : suppression de %s",
                fire_id, entity_entry.entity_id,
            )
            registry.async_remove(entity_entry.entity_id)
            if self._hass.states.get(entity_entry.entity_id) is not None:
                self._hass.states.async_remove(entity_entry.entity_id)
            self._entities.pop(fire_id, None)
            self._details_cache.pop(fire_id, None)
            self._commune_cache.pop(fire_id, None)
            self._permanent_failures.discard(fire_id)
            self._last_seen.pop(fire_id, None)
            self._orphan_refreshed.discard(fire_id)
            self._last_state_change.pop(fire_id, None)
            notified_ids.discard(fire_id)
            if detection_dates.pop(fire_id, None) is not None:
                detection_dates_changed = True
            orphaned += 1

        # Nettoie les éventuels états résiduels 'restored' orphelins dans hass.states
        active_entity_ids = {ent.entity_id for ent in self._entities.values() if hasattr(ent, "entity_id")}
        for state in self._hass.states.async_all("geo_location"):
            if (
                state.attributes.get("restored")
                and state.entity_id.startswith("geo_location.feux_de_foret_")
                and state.entity_id not in active_entity_ids
            ):
                _LOGGER.debug("Nettoyage de l'état résiduel orphelin %s", state.entity_id)
                self._hass.states.async_remove(state.entity_id)

        if orphaned:
            _LOGGER.info("%d entité(s) geo_location orpheline(s) supprimée(s)", orphaned)
        if grace_protected:
            _LOGGER.debug(
                "%d entité(s) absente(s) du flux mais conservée(s) (période de grâce de %s)",
                grace_protected, grace_period,
            )

        detection_store = getattr(self._coordinator, "_detection_store", None)
        if detection_dates_changed and detection_store is not None:
            serialized = {
                fire_id: dt.isoformat() for fire_id, dt in detection_dates.items() if dt is not None
            }
            await detection_store.async_save(serialized)


class FeuDeForetLocationEvent(GeolocationEvent):
    """Une entité par feu. L'icône passe automatiquement de 'en attente' à 'confirmé' dès que le statut change."""

    _attr_should_poll = False
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_has_entity_name = True

    def __init__(self, hass, entry, fire_id, feature, dist_km, details, last_state_change):
        self._hass = hass
        self._entry = entry
        self._fire_id = fire_id
        self._latitude = None
        self._longitude = None
        self._attr_unique_id = f"{entry.entry_id}_fire_{fire_id}"
        self._attr_device_info = device_info_for(entry)
        self._etat = None
        self._statut_detail = None
        self._server_updated_at = None
        self._excerpt = None
        self._last_state_change = last_state_change
        self._confirmed = False
        self._closed_event_fired = False
        self._update_state(feature, dist_km, details, fire_event=False)
        if self._is_extinguished or self._is_false_alarm:
            self._closed_event_fired = True

    def _update_state(self, feature, dist_km, details, fire_event=True):
        props = feature.get("properties", {})
        lat, lng = extract_point_from_feature(feature)
        if lat is not None and lng is not None:
            self._latitude = lat
            self._longitude = lng
        self._statut = details.get("statut") or props.get("statut")
        self._is_early = _is_early(props)
        is_pending = self._statut in PROBABLE_STATUTS

        # Détection de fausse alerte depuis les détails ou le statut
        is_false_alarm = bool(
            self._statut == "fausse_alerte"
            or props.get("statut") == "fausse_alerte"
            or details.get("statut") == "fausse_alerte"
            or (details.get("statut_detail") and "fausse alerte" in str(details.get("statut_detail")).lower())
            or (props.get("etat") == "fausse_alerte")
            or (props.get("title") and "fausse alerte" in str(props.get("title")).lower())
        )

        if is_false_alarm:
            self._confirmed = True
            is_pending = False
            self._statut = "fausse_alerte"
            self._etat = "fausse_alerte"
        elif getattr(self, "_confirmed", False) and is_pending:
            _LOGGER.debug(
                "Feu %s déjà confirmé (%s) : statut 'probable' transitoire ignoré (anti-rebond)",
                self._fire_id, self._etat,
            )
            is_pending = False
            self._confirmed = True
        else:
            self._confirmed = not is_pending

        previous_etat = self._etat
        previous_statut_detail = self._statut_detail

        if details.get("excerpt"):
            self._excerpt = details.get("excerpt")

        if is_false_alarm:
            commune = details.get("commune") or props.get("commune") or commune_from_url(props.get("url"))
            dept = details.get("dept") or props.get("dept") or department_from_url(props.get("url"))
            self._commune = commune
            self._dept = dept
            self._commune_label = commune_with_department(commune, dept)
            self._etat = "fausse_alerte"
            self._statut_detail = details.get("statut_detail") or props.get("statut_detail") or "Fausse alerte"
            self._url = full_url(props.get("url"))
            self._signal_dt = details.get("date")
        elif is_pending:
            commune = details.get("commune") or props.get("commune") or commune_from_url(props.get("url"))
            dept = details.get("dept") or props.get("dept") or department_from_url(props.get("url"))
            self._commune = commune
            self._dept = dept
            self._commune_label = commune_with_department(commune, dept)
            self._etat = None
            self._statut_detail = STATUT_EARLY_LABEL if self._is_early else STATUT_PROBABLE_LABEL
            self._url = full_url(props.get("url"))
            self._signal_dt = details.get("date")
        else:
            commune = details.get("commune") or commune_from_url(props.get("url"))
            dept = details.get("dept") or department_from_url(props.get("url"))
            self._commune = commune
            self._dept = dept
            self._commune_label = commune_with_department(commune, dept)
            self._etat = details.get("etat") or props.get("etat")
            self._statut_detail = details.get("statut_detail") or props.get("statut_detail")
            self._url = full_url(props.get("url"))
            self._signal_dt = details.get("date")

        # Date de mise à jour du statut telle que renvoyée par feuxdeforet.fr lui-même (voir
        # utils._extract_update_timestamp) — prioritaire sur notre suivi local
        # (_last_state_change) dès qu'elle est disponible, car elle reste exacte même si
        # Home Assistant était éteint ou a raté le cycle exact du changement.
        self._server_updated_at = details.get("updated_at")

        self._distance_km = round(dist_km, 1) if dist_km is not None else None
        self._elapsed = elapsed_since(self._signal_dt)
        self._attr_name = self._commune_label
        self._attr_icon = self._icon_for_state()

        if fire_event:
            self._maybe_fire_status_event(previous_etat, previous_statut_detail)

    def _maybe_fire_status_event(self, previous_etat, previous_statut_detail):
        """Émet EVENT_FIRE_STATUS_CHANGED si le statut affiché a réellement changé, et met à
        jour le repli local self._last_state_change[fire_id] — utilisé pour
        etat_change_depuis UNIQUEMENT si feuxdeforet.fr ne fournit pas encore de champ de
        mise à jour reconnu (voir extra_state_attributes ci-dessous, qui priorise toujours
        self._server_updated_at quand disponible).
        """
        if previous_etat == self._etat and previous_statut_detail == self._statut_detail:
            return

        # Un feu éteint ou en fausse alerte ne doit émettre l'événement de clôture qu'une seule fois
        if self._is_extinguished or self._is_false_alarm:
            if getattr(self, "_closed_event_fired", False):
                return
            self._closed_event_fired = True
        else:
            self._closed_event_fired = False

        self._last_state_change[self._fire_id] = dt_util.utcnow()
        self._hass.bus.async_fire(EVENT_FIRE_STATUS_CHANGED, {
            "fire_id": str(self._fire_id),
            "entity_id": self.entity_id,
            "commune": self._commune,
            "departement": self._dept,
            "commune_departement": self._commune_label,
            "statut": self._statut,
            "confirme": self._confirmed,
            "anticipe": self._is_early,
            "etat": self._etat,
            "etat_precedent": previous_etat,
            "etat_label": ETAT_LABELS.get(self._etat, self._etat) if self._etat else self._statut_detail,
            "statut_detail": self._statut_detail,
            "eteint": self._is_extinguished,
            "fausse_alerte": self._is_false_alarm,
            "motif": self._excerpt,
            "url": self._url,
            "latitude": self._latitude,
            "longitude": self._longitude,
            "distance_km": self._distance_km,
            "signale_depuis": self._elapsed if self._elapsed is not None else "date inconnue",
        })

    @property
    def _is_false_alarm(self):
        statut_lower = (self._statut or "").lower()
        detail_lower = (self._statut_detail or "").lower()
        etat_lower = (self._etat or "").lower()
        return "fausse_alerte" in statut_lower or "fausse alerte" in detail_lower or "fausse_alerte" in etat_lower

    def _icon_for_state(self):
        if self._is_false_alarm:
            return "mdi:shield-check"
        if self._is_extinguished:
            return "mdi:fire-off"
        if not self._confirmed:
            return "mdi:fire-alert"
        return "mdi:fire"

    @property
    def _is_extinguished(self):
        if self._etat == "eteint":
            return True
        statut_lower = (self._statut or "").lower()
        if "eteint" in statut_lower or "éteint" in statut_lower:
            return True
        return bool(self._statut_detail and "teint" in str(self._statut_detail).lower())

    def update_from_feature(self, feature, dist_km, details):
        was_confirmed = self._confirmed
        self._update_state(feature, dist_km, details)
        if not was_confirmed and self._confirmed and not self._is_false_alarm and not self._is_extinguished:
            _LOGGER.info("Signalement %s confirmé — passage en feu confirmé (%s)", self._fire_id, self._commune_label)
        self.async_write_ha_state()

    @property
    def status_source_url(self):
        return self._url

    def apply_status_refresh(self, details):
        """Applique le texte de statut final récupéré une fois pour un feu sorti du flux."""
        statut_detail = details.get("statut_detail")
        statut = details.get("statut")
        etat = details.get("etat")
        updated_at = details.get("updated_at")
        excerpt = details.get("excerpt")

        if not statut_detail and not statut and not etat and updated_at is None:
            return

        _LOGGER.info(
            "Feu %s (sorti du flux) : statut final récupéré depuis feuxdeforet.fr -> %s (statut=%s, etat=%s)",
            self._fire_id, statut_detail, statut, etat,
        )
        previous_etat = self._etat
        previous_statut_detail = self._statut_detail

        if statut:
            self._statut = statut
        if etat is not None:
            self._etat = etat
        elif statut_detail:
            self._etat = None

        if statut_detail:
            self._statut_detail = statut_detail
        if excerpt:
            self._excerpt = excerpt
        if updated_at is not None:
            self._server_updated_at = updated_at

        self._attr_icon = self._icon_for_state()
        self._maybe_fire_status_event(previous_etat, previous_statut_detail)
        self.async_write_ha_state()

    @property
    def source(self):
        return DOMAIN

    @property
    def entity_picture(self):
        if self._is_false_alarm or self._is_extinguished:
            return FIRE_EXTINGUISHED_ICON_DATA_URI
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
            "etat": self._etat, "eteint": self._is_extinguished,
            "fausse_alerte": self._is_false_alarm,
            "etat_label": ETAT_LABELS.get(self._etat, self._etat) if self._etat else self._statut_detail,
            "url": self._url, "id": self._fire_id,
        }
        if self._statut_detail:
            attrs["statut_detail"] = self._statut_detail
        if self._excerpt:
            attrs["motif"] = self._excerpt
        attrs["signale_le"] = self._signal_dt.isoformat() if self._signal_dt is not None else "9999-12-31T23:59:59+00:00"
        attrs["signale_depuis"] = self._elapsed if self._elapsed is not None else "date inconnue"

        # Priorité : (1) date de mise à jour fournie par feuxdeforet.fr lui-même — exacte
        # quelle que soit l'activité de Home Assistant au moment du changement — puis (2)
        # repli sur notre suivi local (fire_last_state_change), qui ne capture que les
        # changements survenus pendant que HA tournait, puis (3) date de signalement si le
        # feu n'a jamais changé d'état depuis sa création.
        change_dt = self._server_updated_at or self._last_state_change.get(self._fire_id)
        attrs["etat_change_le"] = change_dt.isoformat() if change_dt is not None else attrs["signale_le"]
        attrs["etat_change_depuis"] = elapsed_since(change_dt) if change_dt is not None else attrs["signale_depuis"]
        return attrs
