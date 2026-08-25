"""PPPP diagnostic sensors (battery, signal, power source, SD usage)."""

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

from .const import DOMAIN, POLL_GROUP_INFO, POLL_GROUP_STATUS
from .device import PPPPDevice
from .entity import PPPPBaseEntity, format_device_type


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
    # Which device poll group keeps this value fresh. None for values that
    # never change (timezone), so they never cause a camera round trip.
    poll_group: str | None = None
    # Extra state attributes, for context that doesn't belong in the state.
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _clock_attrs(props: dict[str, Any]) -> dict[str, Any]:
    """Show the reading the offset was derived from."""
    camera_time = props.get("camera_time")
    return {"camera_time": camera_time.strftime("%Y-%m-%d %H:%M:%S")} if camera_time else {}


def _device_type_attrs(props: dict[str, Any]) -> dict[str, Any]:
    """The raw halves behind the rendered model string.

    Reported even when None: aiopppp's enums come from the vendor apps and are
    incomplete, so "chipType 2, chipTypeName None" is a useful thing to see
    rather than an absent attribute.
    """
    return {
        key: props.get(key)
        for key in ("devType", "devTypeName", "chipType", "chipTypeName")
    }


SENSORS: tuple[PPPPSensorEntityDescription, ...] = (
    PPPPSensorEntityDescription(
        key="battery",
        translation_key="battery",
        poll_group=POLL_GROUP_STATUS,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # JSON cameras report batValue (percent). Binary cameras report
        # batLevel in MILLIVOLTS; aiopppp>=0.3.0 derives batPercent from it
        # (None when externally powered / out of battery range), so use that
        # -- feeding batLevel here showed readings like "4213%".
        value_fn=lambda props: _first(props, "batValue", "batPercent"),
        supported_fn=lambda props: _first(props, "batValue", "batPercent") is not None,
    ),
    PPPPSensorEntityDescription(
        key="signal",
        translation_key="signal",
        # dbm comes out of the binary status block, so it needs the status poll
        # to refresh (it used to be in no poll group at all, back when it was
        # believed to be an unusable field).
        poll_group=POLL_GROUP_STATUS,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda props: _first(props, "signal", "dbm"),
        supported_fn=lambda props: _first(props, "signal", "dbm") is not None,
    ),
    PPPPSensorEntityDescription(
        key="power_source",
        translation_key="power_source",
        poll_group=POLL_GROUP_STATUS,
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
        poll_group=POLL_GROUP_STATUS,
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
        # No poll_group on purpose. The clock response already carries the
        # timezone, so this refreshes for free whenever the info group runs --
        # but a static value should never keep that poll alive by itself.
        #
        # aiopppp reports None when the firmware doesn't actually store a
        # timezone, so the sensor simply isn't created for those cameras.
        value_fn=lambda props: props.get("tz"),
        supported_fn=lambda props: bool(props.get("tz")),
    ),
    PPPPSensorEntityDescription(
        key="clock_offset",
        translation_key="clock_offset",
        poll_group=POLL_GROUP_INFO,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # How far the camera clock is ahead (+) or behind (-) Home Assistant.
        # Reported instead of the camera's time itself: the offset answers the
        # question the sensor exists for ("is the clock right?"), stays put
        # between readings, and can't drift into a plausible-looking lie the
        # way a locally-advanced clock could.
        value_fn=lambda props: props.get("clock_offset"),
        supported_fn=lambda props: props.get("clock_offset") is not None,
        attrs_fn=_clock_attrs,
    ),
    PPPPSensorEntityDescription(
        key="ssid",
        translation_key="ssid",
        poll_group=POLL_GROUP_INFO,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda props: props.get("ssid"),
        supported_fn=lambda props: bool(props.get("ssid")),
    ),
    PPPPSensorEntityDescription(
        key="device_type",
        translation_key="device_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Off by default: the same string is already on the device page, so
        # this exists for the raw numbers behind it, in the attributes.
        entity_registry_enabled_default=False,
        # No poll_group -- a camera's type doesn't change.
        value_fn=format_device_type,
        # Keyed on the raw values, not the rendered name: a camera whose type
        # aiopppp can't name is exactly the one whose numbers are worth having.
        # The state is then "unknown" while the attributes still carry them.
        supported_fn=lambda props: (
            props.get("devType") is not None or props.get("chipType") is not None
        ),
        attrs_fn=_device_type_attrs,
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

    async def async_added_to_hass(self) -> None:
        """Claim the poll group this sensor's value comes from.

        Only enabled entities are ever added, so claiming here is what keeps
        the camera from being polled for data nobody is displaying.
        """
        await super().async_added_to_hass()
        if self.entity_description.poll_group:
            self.async_on_remove(
                self.device.register_poll_group(self.entity_description.poll_group)
            )

    @property
    def native_value(self) -> Any:
        """Return the current value from the camera's last-known properties."""
        return self.entity_description.value_fn(_properties(self.device))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return supporting context, if this sensor provides any."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(_properties(self.device))
