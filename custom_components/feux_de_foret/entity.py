"""Shared base entity for Feux de forêt."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL


def zone_name(entry: ConfigEntry) -> str:
    return entry.options.get(CONF_NAME, entry.data.get(CONF_NAME, DEFAULT_NAME))


def device_info_for(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=zone_name(entry),
        manufacturer=MANUFACTURER,
        model=MODEL,
        configuration_url="https://feuxdeforet.fr",
    )


class FeuxDeForetEntity(CoordinatorEntity):
    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = device_info_for(entry)
        self._attr_has_entity_name = True
