import logging
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "pppp_camera"
PLATFORMS: Final = [Platform.CAMERA]

LOGGER = logging.getLogger(__package__)

ATTR_PAN = "pan"
ATTR_TILT = "tilt"
ATTR_MOVE_MODE = "move_mode"
ATTR_CONTINUOUS_DURATION = "continuous_duration"
ATTR_PRESET = "preset"

CONTINUOUS_MOVE = "ContinuousMove"
RELATIVE_MOVE = "RelativeMove"
ABSOLUTE_MOVE = "AbsoluteMove"
GOTOPRESET_MOVE = "GotoPreset"
STOP_MOVE = "Stop"

DIR_UP = "UP"
DIR_DOWN = "DOWN"
DIR_LEFT = "LEFT"
DIR_RIGHT = "RIGHT"

SERVICE_PTZ = "ptz"
SERVICE_REBOOT = "reboot"

SOURCE_DISCOVERY_CONFIRM = "discovery_confirm"

CONF_DEFAULTS = "defaults"
CONF_IP = "ip"
CONF_DURATION = "duration"
CONF_INTERVAL = "interval"
CONF_LAMP = "lamp"
CONF_IDLE_DISCONNECT_DELAY = "idle_disconnect_delay"

# Seconds to keep a camera session open after the last in-flight operation
# finishes. Keeping it warm lets back-to-back commands (e.g. PTZ bursts) reuse
# the session and avoids tearing the connection down before a fire-and-forget
# command has been delivered. 0 disconnects immediately.
DEFAULT_IDLE_DISCONNECT_DELAY = 5
