"""PPPP diagnostic sensors (battery, signal, uptime)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
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
    # Re-render on HA's poll interval. Only for values derived from elapsed
    # time (the camera clock); polling never touches the camera itself.
    poll: bool = False


def _camera_time(props: dict[str, Any]) -> str | None:
    """The camera's own clock, advanced by the time since it was read.

    The cameras never push updates and are only queried on connect, so a raw
    reading would sit frozen at whatever it said during setup. Projecting it
    forward keeps it comparable with local time at a glance -- a camera whose
    clock or timezone is wrong stays visibly offset.
    """
    read = props.get("camera_time")
    read_at = props.get("camera_time_read_at")
    if read is None or read_at is None:
        return None
    elapsed = max(0.0, time.monotonic() - read_at)
    return (read + timedelta(seconds=elapsed)).strftime("%Y-%m-%d %H:%M:%S")


SENSORS: tuple[PPPPSensorEntityDescription, ...] = (
    PPPPSensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # JSON cameras report batValue (percent). Binary cameras report
        # batLevel in MILLIVOLTS; aiopppp>=0.4.0 derives batPercent from it
        # (None when externally powered / out of battery range), so use that
        # -- feeding batLevel here showed readings like "4213%".
        value_fn=lambda props: _first(props, "batValue", "batPercent"),
        supported_fn=lambda props: _first(props, "batValue", "batPercent") is not None,
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
        # Some firmwares report a garbage (negative) uptime; only expose it
        # when it is a sane non-negative value.
        supported_fn=lambda props: isinstance(props.get("uptime"), int)
        and props["uptime"] >= 0,
    ),
    PPPPSensorEntityDescription(
        key="power_source",
        translation_key="power_source",
        device_class=SensorDeviceClass.ENUM,
        options=["external", "battery"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda props: (
            "external" if props.get("externalPower") else "battery"
        ),
        # Mains-only cameras don't report power state at all: they leave a
        # placeholder in batLevel (8000) and a zero powerSupply bit, which
        # rendered as a confident (and wrong) "Battery". Only expose this
        # where a real battery reading proves the fields are populated.
        supported_fn=lambda props: _first(props, "batValue", "batPercent") is not None,
    ),
    PPPPSensorEntityDescription(
        key="sd_usage",
        translation_key="sd_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # totalSize/usedSize are in the same (unknown) unit, so a ratio is
        # meaningful even if the absolute unit isn't.
        value_fn=lambda props: round(
            100 * props["usedSize"] / props["totalSize"]
        )
        if props.get("totalSize")
        else None,
        supported_fn=lambda props: bool(props.get("totalSize")),
    ),
    PPPPSensorEntityDescription(
        key="timezone",
        translation_key="timezone",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # aiopppp reports None when the firmware doesn't actually store a
        # timezone, so the sensor simply isn't created for those cameras.
        value_fn=lambda props: props.get("tz"),
        supported_fn=lambda props: bool(props.get("tz")),
    ),
    PPPPSensorEntityDescription(
        key="camera_time",
        translation_key="camera_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        poll=True,
        value_fn=_camera_time,
        supported_fn=lambda props: props.get("camera_time") is not None,
    ),
    PPPPSensorEntityDescription(
        key="ssid",
        translation_key="ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda props: props.get("ssid"),
        supported_fn=lambda props: bool(props.get("ssid")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PPPP sensor platform."""
    device: PPPPDevice = hass.data[DOMAIN][config_entry.unique_id]
    props = _properties(device)
    async_add_entities(
        PPPPSensor(device, description)
        for description in SENSORS
        if description.supported_fn(props)
    )


def _properties(device: PPPPDevice) -> dict[str, Any]:
    """Status-block properties plus the separately-fetched extras."""
    return {**device.device.properties, **device.extra_info}


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
        # Overrides the base class's push-only default for time-derived values.
        self._attr_should_poll = description.poll

    async def async_update(self) -> None:
        """Re-render only. Polling must never reach out to the camera: these
        devices accept a single client, so waking one for a diagnostic value
        would fight with streaming."""

    @property
    def native_value(self) -> Any:
        """Return the current value from the camera's last-known properties."""
        return self.entity_description.value_fn(_properties(self.device))
