"""The PPPP IP Camera integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    Platform,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PLATFORM,
    CONF_DISCOVERY,
    CONF_ENABLED,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
import voluptuous as vol
from aiopppp import NotConnectedError

from .camera import PPPPCamera
from .discovery import async_start_discovery
from .config_helpers import get_config
from .const import (
    DOMAIN,
    LOGGER,
    PLATFORMS,
    CONF_DEFAULTS,
    CONF_IP,
    CONF_DURATION,
    CONF_INTERVAL,
    CONF_LAMP,
    CONF_IDLE_DISCONNECT_DELAY,
    CONF_STATUS_POLL_INTERVAL,
    DEFAULT_IDLE_DISCONNECT_DELAY,
    DEFAULT_STATUS_POLL_INTERVAL,
)


from .device import PPPPDevice

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_DEFAULTS, default={}): vol.Schema(
                    {
                        vol.Optional(CONF_USERNAME, default="admin"): cv.string,
                        vol.Optional(CONF_PASSWORD, default="6666"): cv.string,
                    }
                ),
                vol.Optional(CONF_PLATFORM, default={}): vol.Schema(
                    {
                        vol.Optional(CONF_LAMP, default=Platform.SWITCH): vol.In(
                            [Platform.SWITCH, Platform.LIGHT, Platform.BUTTON]
                        ),
                    }
                ),
                vol.Optional(CONF_DISCOVERY, default={}): vol.Schema(
                    {
                        vol.Optional(CONF_ENABLED, default=True): cv.boolean,
                        vol.Optional(CONF_DURATION, default=10): cv.positive_int,
                        vol.Optional(CONF_INTERVAL, default=600): cv.positive_int,
                        vol.Optional(CONF_IP): vol.Any(cv.string, [cv.string]),
                    }
                ),
                vol.Optional(
                    CONF_IDLE_DISCONNECT_DELAY,
                    default=DEFAULT_IDLE_DISCONNECT_DELAY,
                ): vol.All(vol.Coerce(int), vol.Range(min=0)),
                vol.Optional(
                    CONF_STATUS_POLL_INTERVAL,
                    default=DEFAULT_STATUS_POLL_INTERVAL,
                ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)
"""
configuration.yaml example:

pppp_camera:
    defaults:
        username: admin
        password: 6666
    platform:
        lamp: switch    # one of [switch, light, button]
    discovery:
        enabled: true
        duration: 10    # seconds to listen for devices during each discovery
        interval: 600   # seconds between discovery attempts
        ip:             # list of IPs to limit discovery to
            - 192.168.1.1
            - 192.168.1.2
            - 192.168.1.3
        # or single IP can also be specified (usually broadcast address)
        ip: 192.168.1.255
        # if 'ip' is not specified, discovery will listen on all interfaces
    idle_disconnect_delay: 5    # seconds to keep a session warm after the last
                                # operation (0 = disconnect immediately)
"""


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    # init storage for registries
    hass.data[DOMAIN] = {}

    # load optional global registry config
    cfg = config if DOMAIN in config else CONFIG_SCHEMA({DOMAIN: {}})
    hass.data[DOMAIN]["config"] = cfg[DOMAIN]
    LOGGER.debug("Config: %s", get_config(hass))

    await async_start_discovery(hass)

    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    device = PPPPDevice(hass, config_entry)
    try:
        await device.async_setup()
    except (TimeoutError, NotConnectedError) as err:
        # NotConnectedError is raised when the camera is found but the session is
        # lost during connect (e.g. P2pRdy/handshake timeout) -- retry, don't fail.
        # device.device may not exist yet if setup failed very early; guard it.
        if getattr(device, "device", None) is not None:
            await device.device.close()
        raise ConfigEntryNotReady(
            f"Could not connect to camera {device.host}: {err}"
        ) from err

    hass.data[DOMAIN][config_entry.unique_id] = device

    device.platforms = [
        Platform.CAMERA,
        Platform.BUTTON,
        Platform.LIGHT,
        Platform.SWITCH,
        Platform.SENSOR,
        Platform.SELECT,
    ]

    await hass.config_entries.async_forward_entry_setups(config_entry, device.platforms)

    # PPPPDevice.async_setup() already registers an options-update listener that
    # reloads the entry, so don't register a second one here (it would reload twice).
    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, device.async_stop)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    device: PPPPDevice | None = hass.data.get(DOMAIN, {}).get(entry.unique_id)
    # Unload the platforms that were actually set up (camera + lamp + button),
    # not just PLATFORMS (camera only) -- otherwise the lamp/button entities are
    # orphaned on unload/reload.
    platforms = device.platforms if device and device.platforms else PLATFORMS
    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unloaded and device is not None:
        # Tear the warm session down and drop the reference so nothing leaks
        # across reloads.
        await device.async_stop()
        hass.data[DOMAIN].pop(entry.unique_id, None)
    return unloaded
