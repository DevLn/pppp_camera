"""PPPP diagnostic sensors (battery, signal, uptime)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import PPPPDevice
from .entity import PPPPBaseEntity


def _first(props: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-None property among keys."""
    for key in keys:
        value = props.get(key)
        if value is not None:
            return value
    return None


@dataclass(frozen=True, kw_only=True)
class PPPPSensorEntityDescription(SensorEntityDescription):
    """Describes a PPPP sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any]
    supported_fn: Callable[[dict[str, Any]], bool]


SENSORS: tuple[PPPPSensorEntityDescription, ...] = (
    PPPPSensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # JSON cameras report batValue, binary cameras batLevel.
        value_fn=lambda props: _first(props, "batValue", "batLevel"),
        supported_fn=lambda props: _first(props, "batValue", "batLevel") is not None,
    ),
    PPPPSensorEntityDescription(
        key="signal",
        translation_key="signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda props: _first(props, "signal", "dbm"),
        supported_fn=lambda props: _first(props, "signal", "dbm") is not None,
    ),
    PPPPSensorEntityDescription(
        key="uptime",
        translation_key="uptime",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda props: props.get("uptime"),
        supported_fn=lambda props: props.get("uptime") is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PPPP sensor platform."""
    device: PPPPDevice = hass.data[DOMAIN][config_entry.unique_id]
    props = device.device.properties
    async_add_entities(
        PPPPSensor(device, description)
        for description in SENSORS
        if description.supported_fn(props)
    )


class PPPPSensor(PPPPBaseEntity, SensorEntity):
    """A PPPP diagnostic sensor.

    These cameras don't push updates, so values reflect the last-fetched
    properties and refresh on the availability signal.
    """

    entity_description: PPPPSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self, device: PPPPDevice, description: PPPPSensorEntityDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self.entity_description = description
        self._attr_unique_id = f"{self.device.dev_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the current value from the camera's last-known properties."""
        return self.entity_description.value_fn(self.device.device.properties)
