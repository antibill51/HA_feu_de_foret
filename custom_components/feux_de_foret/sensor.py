"""Sensor platform: fire counts/distance within a zone, plus diagnostic freshness sensor."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .const import (
    DOMAIN, ONGOING_STATUTS, PROBABLE_STATUTS, ONGOING_ETATS,
    CONF_RADIUS, CONF_LATITUDE, CONF_LONGITUDE,
    ETAT_LABELS, STATUT_PROBABLE_LABEL, STATUT_EARLY_LABEL,
)
from .entity import FeuxDeForetEntity
from .utils import full_url, commune_from_url, department_from_url, commune_with_department, elapsed_since, extract_point_from_feature


def _is_early(props):
    return str(props.get("id", "")).startswith("early-")


def _is_confirmed(props):
    return props.get("statut") in ONGOING_STATUTS and props.get("etat") in ONGOING_ETATS


def _is_pending(props):
    return props.get("statut") in PROBABLE_STATUTS


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        FeuxNearbyCountSensor(coordinator, entry),
        FeuxConfirmedNationalSensor(coordinator, entry),
        FeuxPendingNationalSensor(coordinator, entry),
        FeuxClosestSensor(coordinator, entry),
        FeuxLastUpdateSensor(coordinator, entry),
    ])


class FeuxBaseSensor(FeuxDeForetEntity, SensorEntity):
    @property
    def _radius_km(self):
        return self._entry.options.get(CONF_RADIUS, self._entry.data.get(CONF_RADIUS, 30))

    @property
    def _home_lat(self):
        return self._entry.data.get(CONF_LATITUDE)

    @property
    def _home_lng(self):
        return self._entry.data.get(CONF_LONGITUDE)

    def _details_for(self, fire_id):
        cache = getattr(self.coordinator, "fire_details", {})
        return cache.get(fire_id, {})

    def _effective_details_for(self, fire_id):
        details = dict(self._details_for(fire_id) or {})
        if details.get("date") is None:
            detection_dates = getattr(self.coordinator, "fire_detection_dates", {})
            detected_at = detection_dates.get(fire_id)
            if detected_at is None:
                detected_at = dt_util.utcnow()
                detection_dates[fire_id] = detected_at
            details["date"] = detected_at
        return details

    def _confirmed_with_distance(self):
        results = []
        for feature in self.coordinator.data or []:
            props = feature.get("properties", {})
            if not _is_confirmed(props):
                continue
            lat, lng = extract_point_from_feature(feature)
            if lat is None or lng is None:
                continue
            dist_m = distance(self._home_lat, self._home_lng, lat, lng)
            dist_km = round(dist_m / 1000, 1) if dist_m is not None else None
            results.append((dist_km, props, lat, lng))
        return results

    def _all_relevant_with_distance(self):
        results = []
        for feature in self.coordinator.data or []:
            props = feature.get("properties", {})
            if not (_is_confirmed(props) or _is_pending(props)):
                continue
            lat, lng = extract_point_from_feature(feature)
            if lat is None or lng is None:
                continue
            dist_m = distance(self._home_lat, self._home_lng, lat, lng)
            dist_km = round(dist_m / 1000, 1) if dist_m is not None else None
            results.append((dist_km, props, lat, lng))
        return results

    def _etat_label_for(self, props, details):
        if details.get("statut_detail"):
            return details["statut_detail"]
        if _is_early(props):
            return STATUT_EARLY_LABEL
        if props.get("statut") in PROBABLE_STATUTS:
            return STATUT_PROBABLE_LABEL
        return ETAT_LABELS.get(props.get("etat"), props.get("etat"))


class FeuxNearbyCountSensor(FeuxBaseSensor):
    """Compte les feux confirmés ET les signalements en attente dans le rayon configuré.

    On inclut volontairement les signalements non confirmés ("probable") : mieux vaut
    remonter une alerte tôt, avant validation officielle par feuxdeforet.fr, plutôt que
    d'attendre une confirmation qui peut prendre du temps pendant un départ de feu actif.
    """

    _attr_icon = "mdi:fire-alert"
    _attr_native_unit_of_measurement = "feux"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearby_count"
        self._attr_name = "Feux en cours à proximité"

    def _relevant_with_distance(self):
        """Feux confirmés et signalements en attente, avec leur distance depuis le centre."""
        return self._all_relevant_with_distance()

    @property
    def native_value(self):
        nearby = [d for d, *_ in self._relevant_with_distance() if d is not None and d <= self._radius_km]
        return len(nearby)

    @property
    def extra_state_attributes(self):
        nearby = []
        for d, p, *_ in self._relevant_with_distance():
            if d is None or d > self._radius_km:
                continue
            fire_id = str(p.get("id"))
            details = self._effective_details_for(fire_id)
            commune = details.get("commune") or commune_from_url(p.get("url"))
            dept = details.get("dept") or department_from_url(p.get("url"))
            signal_dt = details.get("date")
            nearby.append({
                "commune": commune, "departement": dept,
                "commune_departement": commune_with_department(commune, dept),
                "commune_url": full_url(p.get("url")) if _is_confirmed(p) else None,
                "distance_km": d, "etat": p.get("etat"), "etat_label": self._etat_label_for(p, details),
                "confirme": _is_confirmed(p),
                "signale_depuis": elapsed_since(signal_dt) if signal_dt is not None else "date inconnue",
                "signale_le": signal_dt.isoformat() if signal_dt is not None else "9999-12-31T23:59:59+00:00",
            })
        return {"radius_km": self._radius_km, "fires": nearby}


class FeuxConfirmedNationalSensor(FeuxBaseSensor):
    _attr_icon = "mdi:fire"
    _attr_native_unit_of_measurement = "feux"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_confirmed_national"
        self._attr_name = "Feux confirmés"

    @property
    def native_value(self):
        return len(self._confirmed_with_distance())


class FeuxPendingNationalSensor(FeuxBaseSensor):
    _attr_icon = "mdi:fire-alert"
    _attr_native_unit_of_measurement = "feux"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_pending_national"
        self._attr_name = "Signalements en attente"

    @property
    def native_value(self):
        return sum(1 for f in self.coordinator.data or [] if _is_pending(f.get("properties", {})))

    @property
    def extra_state_attributes(self):
        anticipes = sum(
            1 for f in self.coordinator.data or []
            if _is_pending(f.get("properties", {})) and _is_early(f.get("properties", {}))
        )
        return {"dont_signalements_anticipes": anticipes}


class FeuxClosestSensor(FeuxBaseSensor):
    _attr_icon = "mdi:map-marker-distance"
    _attr_native_unit_of_measurement = "km"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_closest_distance"
        self._attr_name = "Distance du feu le plus proche"

    @property
    def native_value(self):
        distances = [d for d, *_ in self._all_relevant_with_distance() if d is not None]
        return min(distances) if distances else None

    @property
    def extra_state_attributes(self):
        entries = sorted(
            [(d, p) for d, p, *_ in self._all_relevant_with_distance() if d is not None],
            key=lambda x: x[0],
        )
        if not entries:
            return {}
        dist, props = entries[0]
        fire_id = str(props.get("id"))
        details = self._effective_details_for(fire_id)
        commune = details.get("commune") or commune_from_url(props.get("url"))
        dept = details.get("dept") or department_from_url(props.get("url"))
        attrs = {
            "commune": commune, "departement": dept,
            "commune_departement": commune_with_department(commune, dept),
            "url": full_url(props.get("url")),
            "etat": props.get("etat"), "etat_label": self._etat_label_for(props, details),
        }
        signal_dt = details.get("date")
        attrs["signale_le"] = signal_dt.isoformat() if signal_dt is not None else "9999-12-31T23:59:59+00:00"
        attrs["signale_depuis"] = elapsed_since(signal_dt) if signal_dt is not None else "date inconnue"
        return attrs


class FeuxLastUpdateSensor(FeuxBaseSensor):
    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_update"
        self._attr_name = "Dernière actualisation des données"
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        return getattr(self.coordinator, "last_fetch_success", None)

    @property
    def extra_state_attributes(self):
        last_success = getattr(self.coordinator, "last_fetch_success", None)
        next_refresh = None
        if last_success and self.coordinator.update_interval:
            next_refresh = (last_success + self.coordinator.update_interval).isoformat()
        return {
            "nombre_de_feux_recus": len(self.coordinator.data or []),
            "prochain_rafraichissement_prevu": next_refresh,
            "source_des_donnees": "feuxdeforet.fr",
        }
