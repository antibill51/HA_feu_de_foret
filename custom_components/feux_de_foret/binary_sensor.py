"""Binary sensor: alert on/off if a fire (confirmed or pending) is within radius."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.location import distance

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    DOMAIN,
    ONGOING_ETATS,
    ONGOING_STATUTS,
    PROBABLE_STATUTS,
)
from .entity import FeuxDeForetEntity
from .utils import extract_point_from_feature


def _is_confirmed(props):
    return props.get("statut") in ONGOING_STATUTS and props.get("etat") in ONGOING_ETATS


def _is_pending(props):
    return props.get("statut") in PROBABLE_STATUTS


def _is_relevant(props):
    """Un feu compte pour l'alerte de proximité, qu'il soit confirmé ou seulement signalé."""
    return _is_confirmed(props) or _is_pending(props)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FeuxAlertBinarySensor(coordinator, entry)])


class FeuxAlertBinarySensor(FeuxDeForetEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_icon = "mdi:fire-alert"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_alert"
        self._attr_name = "Alerte feu de forêt à proximité"

    @property
    def _radius_km(self):
        return self._entry.options.get(CONF_RADIUS, self._entry.data.get(CONF_RADIUS, 30))

    @property
    def is_on(self):
        home_lat = self._entry.data.get(CONF_LATITUDE)
        home_lng = self._entry.data.get(CONF_LONGITUDE)
        for feature in self.coordinator.data or []:
            props = feature.get("properties", {})
            # Un feu confirmé ou un signalement en attente déclenche l'alerte dès qu'il
            # entre dans le rayon configuré : mieux vaut prévenir tôt, même avant
            # confirmation officielle par feuxdeforet.fr.
            if not _is_relevant(props):
                continue
            lat, lng = extract_point_from_feature(feature)
            if lat is None or lng is None:
                continue
            dist_m = distance(home_lat, home_lng, lat, lng)
            if dist_m is not None and dist_m / 1000 <= self._radius_km:
                return True
        return False
