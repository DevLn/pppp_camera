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
ATTR_ACTION = "action"

PRESET_ACTION_GOTO = "goto"
PRESET_ACTION_SET = "set"

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
SERVICE_PTZ_PRESET = "ptz_preset"
SERVICE_REBOOT = "reboot"
SERVICE_TALK = "talk"

ATTR_MEDIA = "media"

SOURCE_DISCOVERY_CONFIRM = "discovery_confirm"

CONF_DEFAULTS = "defaults"
CONF_IP = "ip"
CONF_DURATION = "duration"
CONF_INTERVAL = "interval"
CONF_LAMP = "lamp"
CONF_IDLE_DISCONNECT_DELAY = "idle_disconnect_delay"
CONF_STATUS_POLL_INTERVAL = "status_poll_interval"
CONF_INFO_POLL_INTERVAL = "info_poll_interval"

# Poll groups. Entities register the group they read from when they are added
# to Home Assistant, and a group is only polled while something is actually
# using it -- a camera with no battery and no SD card never gets a status
# poll, and disabling those entities stops it too.
POLL_GROUP_STATUS = "status"
POLL_GROUP_INFO = "info"

# Maps a lamp entity key to the camera property whose presence proves the
# camera has that lamp at all. Both keys are always present on binary cameras,
# so this decides which entities exist -- not what state they are in.
LAMP_STATE_PROPERTY = {"white_lamp": "lamp", "ir_lamp": "icut"}

# Maps a lamp entity key to the property carrying its *real* state, from the
# status block's function bitmap. None on firmwares that don't populate it
# (PTZA), which is exactly what LAMP_STATE_PROPERTY can't tell you: `lamp` is
# derived from an unpopulated word and reads 0 there, and `icut` sits at 1
# whatever the IR is doing. So a lamp reads live only where this is not None.
LAMP_REPORTED_PROPERTY = {"white_lamp": "funcFillLight", "ir_lamp": "funcIrLed"}

# Seconds to keep a camera session open after the last in-flight operation
# finishes. Keeping it warm lets back-to-back commands (e.g. PTZ bursts) reuse
# the session and avoids tearing the connection down before a fire-and-forget
# command has been delivered. 0 disconnects immediately.
DEFAULT_IDLE_DISCONNECT_DELAY = 5

# How often to re-read the camera status block (battery, signal, SD usage).
# Nothing is pushed by these cameras, so without this the values stay frozen
# at whatever they were when the session first connected.
#
# Each poll opens a short session, so keep it infrequent: battery-powered
# models can only sleep between connections. 0 disables polling entirely.
DEFAULT_STATUS_POLL_INTERVAL = 300

# How often to re-read values that need their own commands (camera clock,
# Wi-Fi SSID). These barely change -- the SSID only when the camera is
# re-provisioned -- so this is deliberately much slower than the status poll.
DEFAULT_INFO_POLL_INTERVAL = 3600

# Pause between setting the camera clock and reading it back. These cameras
# ignore commands that arrive immediately after another, and set_datetime()
# already performs a read of its own.
SYNC_READBACK_DELAY = 2.0
