"""PPPP device abstraction."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import time

import aiopppp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .config_helpers import get_idle_disconnect_delay, get_status_poll_interval
from .const import DOMAIN, LOGGER


class PPPPDevice:
    """Manages a PPPP device."""

    device: aiopppp.Device

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the device."""
        self.hass: HomeAssistant = hass
        self.config_entry: ConfigEntry = config_entry
        self._original_options = dict(config_entry.options)
        self.available: bool = True
        self.info: dict = {}
        # Values that aren't in the status block and need their own commands
        # (clock, Wi-Fi, video params). Refreshed on connect; entities read the
        # last-known values because these cameras never push updates.
        self.extra_info: dict = {}
        self.platforms: list[Platform] = []

        self._connected_num = 0
        self._dt_diff_seconds: float = 0

        # Connection lifecycle: serialize connect/close and keep the session
        # warm for a short idle window so back-to-back operations reuse it.
        self._lock = asyncio.Lock()
        self._idle_unload_task: asyncio.Task | None = None
        self._idle_disconnect_delay: int = get_idle_disconnect_delay(hass, config_entry)
        self._status_poll_interval: int = get_status_poll_interval(hass, config_entry)
        self._status_poll_task: asyncio.Task | None = None

        # Entities subscribe to these signals to refresh availability / stream state.
        self.signal_available = f"{DOMAIN}_{config_entry.entry_id}_available"
        self.signal_streaming = f"{DOMAIN}_{config_entry.entry_id}_streaming"

    def _set_available(self, value: bool) -> None:
        """Update availability and notify entities only when it changes."""
        if self.available != value:
            self.available = value
            async_dispatcher_send(self.hass, self.signal_available)

    @callback
    def _on_video_state_change(self, is_streaming: bool) -> None:
        """Forward the library's streaming-state change to subscribed entities."""
        async_dispatcher_send(self.hass, self.signal_streaming)

    async def _async_update_listener(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Handle options update."""
        if self._original_options != entry.options:
            hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    @property
    def host(self) -> str:
        """Return the host of this device."""
        return self.config_entry.options[CONF_HOST]

    @property
    def username(self) -> str:
        """Return the username of this device."""
        return self.config_entry.options.get(CONF_USERNAME)

    @property
    def password(self) -> str:
        """Return the password of this device."""
        return self.config_entry.options.get(CONF_PASSWORD)

    @property
    def dev_id(self) -> str:
        """Return the dev_id of this device."""
        return self.device.descriptor.dev_id.dev_id

    async def connect(self):
        """Connect to the device, reusing a warm session when available."""
        async with self._lock:
            # A new user cancels any pending idle teardown and reuses the session.
            self._cancel_idle_unload()
            self._connected_num += 1
            if not self.device.is_connected:
                try:
                    await self.device.connect()
                except Exception:
                    # ensure_connected() skips close() when connect() raises, so
                    # roll back the reference we just took to avoid leaking it.
                    self._connected_num -= 1
                    self._set_available(False)
                    raise
            self._set_available(True)

    async def close(self):
        """Release a connection reference; tear down only after an idle window."""
        async with self._lock:
            if not self._connected_num:
                return
            self._connected_num -= 1
            if self._connected_num == 0:
                # Defer teardown instead of closing inline. A command arriving
                # within the idle window reuses the live session, and a
                # fire-and-forget command is not cut off by an immediate Close.
                self._cancel_idle_unload()
                self._idle_unload_task = asyncio.create_task(self._idle_unload())

    async def _idle_unload(self) -> None:
        """Close the session once it has been idle for the configured delay."""
        try:
            await asyncio.sleep(self._idle_disconnect_delay)
            async with self._lock:
                # Re-check under the lock: a user may have reconnected during the wait.
                if self._connected_num == 0 and self.device.is_connected:
                    await self.device.close()
                self._idle_unload_task = None
        except asyncio.CancelledError:
            # Cancellation can arrive during the sleep or while awaiting the lock;
            # either way there is nothing to clean up (a reconnect took over).
            return

    def _cancel_idle_unload(self) -> None:
        """Cancel a pending idle teardown, if any."""
        if self._idle_unload_task and not self._idle_unload_task.done():
            self._idle_unload_task.cancel()
        self._idle_unload_task = None

    async def async_setup(self) -> None:
        """Set up the device."""
        self.device = get_device(
            self.hass,
            host=self.config_entry.options[CONF_HOST],
            username=self.config_entry.options[CONF_USERNAME],
            password=self.config_entry.options[CONF_PASSWORD],
            on_video_state_change=self._on_video_state_change,
        )

        async with self.ensure_connected():
            self.info = self.device.properties
            await self._async_fetch_extra_info()

        self._start_status_poll()
        self.config_entry.async_on_unload(self._stop_status_poll)

        self.config_entry.async_on_unload(
            self.config_entry.add_update_listener(self._async_update_listener)
        )

    async def async_stop(self, event=None):
        """Shut it all down."""
        self._stop_status_poll()
        async with self._lock:
            self._cancel_idle_unload()
            self._connected_num = 0
            await self.device.close()

    async def _async_fetch_extra_info(self) -> None:
        """Read values that aren't part of the status block.

        Every one of these is optional: cameras answer a different subset
        (and some answer none), so each failure is recorded as a missing key
        rather than aborting setup. Must be called with a live connection.
        """
        from aiopppp.packets import parse_datetime_block, parse_wifi_settings

        session = self.device.session
        info: dict = {}

        if (get_datetime := getattr(session, "get_datetime", None)) is not None:
            try:
                decoded = parse_datetime_block(await get_datetime(timeout=4))
                if local := decoded.get("local"):
                    # Store the camera clock together with the monotonic
                    # instant it was read, so the sensor can project it
                    # forward instead of showing a frozen timestamp.
                    info["camera_time"] = dt.datetime.strptime(local, "%Y-%m-%d %H:%M:%S")
                    info["camera_time_read_at"] = time.monotonic()
            except Exception as err:  # noqa: BLE001 - optional, never fatal
                LOGGER.debug("%s: datetime unavailable: %s", self.dev_id, err)

        if (get_wifi := getattr(session, "get_wifi_settings", None)) is not None:
            try:
                wifi = parse_wifi_settings(await get_wifi(timeout=4))
                if ssid := wifi.get("ssid"):
                    info["ssid"] = ssid
            except Exception as err:  # noqa: BLE001 - optional, never fatal
                LOGGER.debug("%s: wifi settings unavailable: %s", self.dev_id, err)

        # Video parameters are only populated while the stream runs: an idle
        # camera answers VIDEOPARAM_GET with an all-zero table, which would
        # read back as a confident (and wrong) QVGA. Keep whatever we already
        # know instead, and refresh once streaming starts.
        if (previous := self.extra_info.get("resolution")) is not None:
            info["resolution"] = previous
        if self._is_streaming:
            info.pop("resolution", None)
            if (value := await self._async_read_resolution()) is not None:
                info["resolution"] = value

        self.extra_info = info

    @property
    def _is_streaming(self) -> bool:
        """True while the camera is actively sending video."""
        return bool(self.device.is_connected and self.device.session.is_video_requested)

    async def _async_read_resolution(self) -> int | None:
        """Read the current resolution, or None if the camera won't say.

        Repeated parameter reads are flaky on these cameras (they simply stop
        answering), so a failure is never fatal -- the caller keeps the last
        known value.
        """
        session = self.device.session
        get_param = getattr(session, "get_video_param_value", None)
        if get_param is None:
            return None
        try:
            return await get_param("resolution", timeout=4)
        except Exception as err:  # noqa: BLE001 - optional, never fatal
            LOGGER.debug("%s: resolution unavailable: %s", self.dev_id, err)
            return None

    async def async_refresh_resolution(self) -> bool:
        """Re-read the resolution while streaming. True if the value changed."""
        if not self._is_streaming:
            return False
        value = await self._async_read_resolution()
        if value is None or value == self.extra_info.get("resolution"):
            return False
        self.extra_info["resolution"] = value
        return True

    async def async_refresh_extra_info(self) -> None:
        """Re-read the extra info and notify entities."""
        async with self.ensure_connected():
            await self._async_fetch_extra_info()
        async_dispatcher_send(self.hass, self.signal_available)

    async def async_refresh_status(self) -> None:
        """Re-read the status block (battery, power source, uptime, SD usage).

        The cameras never push updates and the library only reads the status
        once, during session setup, so these values would otherwise stay frozen
        at whatever they were when the session first connected.
        """
        async with self.ensure_connected():
            session = self.device.session
            get_status = getattr(session, "get_status", None)
            if get_status is not None:
                status = await get_status()
                # Keep the auth flag the session recorded at setup; get_status()
                # doesn't return it and entities shouldn't see it disappear.
                status.setdefault("auth", session.dev_properties.get("auth"))
                session.dev_properties = status
                self.device.properties = status
                self.info = status
            await self._async_fetch_extra_info()
        async_dispatcher_send(self.hass, self.signal_available)

    async def _status_poll_loop(self) -> None:
        """Refresh the status on a fixed interval until cancelled."""
        while True:
            try:
                await asyncio.sleep(self._status_poll_interval)
                await self.async_refresh_status()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - a poll failure is not fatal
                # An unreachable camera is already reflected by availability;
                # keep polling so the values recover on their own.
                LOGGER.debug("%s: status poll failed: %s", self.dev_id, err)

    def _start_status_poll(self) -> None:
        if not self._status_poll_interval:
            LOGGER.debug("%s: status polling disabled", self.dev_id)
            return
        self._status_poll_task = self.hass.async_create_background_task(
            self._status_poll_loop(), f"{DOMAIN}_status_poll_{self.dev_id}"
        )

    def _stop_status_poll(self) -> None:
        if self._status_poll_task and not self._status_poll_task.done():
            self._status_poll_task.cancel()
        self._status_poll_task = None

    async def async_set_resolution(self, value: str) -> None:
        """Set the video resolution and remember the new value."""
        async with self.ensure_connected():
            session = self.device.session
            set_resolution = getattr(session, "set_resolution", None)
            if set_resolution is None:
                raise HomeAssistantError("This camera does not support setting the resolution")
            await set_resolution(value)
        # The camera doesn't report a param change back, so record what we set;
        # a later refresh overwrites it with whatever the camera reports.
        from aiopppp.const import VideoResolution

        self.extra_info["resolution"] = VideoResolution[f"VIDEO_RESOLUTION_{value.upper()}"].value

    async def async_white_light_toggle(self, data):
        """Turn on the white light."""
        async with self.ensure_connected():
            await self.device.session.toggle_whitelight(data)

    async def async_white_light_on(self, data):
        """Turn on the white light."""
        await self.async_white_light_toggle(1)

    async def async_white_light_off(self, data):
        """Turn on the white light."""
        await self.async_white_light_toggle(0)

    async def async_ir_light_toggle(self, data):
        """Turn on the white light."""
        async with self.ensure_connected():
            await self.device.session.toggle_ir(data)

    async def async_ir_light_on(self, data):
        """Turn on the white light."""
        await self.async_ir_light_toggle(1)

    async def async_ir_light_off(self, data):
        """Turn on the white light."""
        await self.async_ir_light_toggle(0)

    async def async_reboot(self, data) -> None:
        """Send out a SystemReboot command."""
        async with self.ensure_connected():
            await self.device.reboot()

    async def async_ptz_preset(self, index: int, action: str) -> None:
        """Go to or store a PTZ preset (binary-protocol cameras)."""
        async with self.ensure_connected():
            session = self.device.session
            if action == "set":
                await session.ptz_set_preset(index)
            else:
                await session.ptz_goto_preset(index)

    async def async_talk(self, url: str) -> None:
        """Play an audio URL to the camera speaker (talk-back).

        The camera wants 8 kHz mono G.711; ffmpeg transcodes arbitrary media
        to raw 16-bit PCM at that rate and the session encodes/frames each
        chunk. Chunks are paced in real time so the camera's small jitter
        buffer isn't flooded.
        """
        from homeassistant.components.ffmpeg import get_ffmpeg_manager

        async with self.ensure_connected():
            session = self.device.session
            send_audio = getattr(session, "send_audio", None)
            start_talk = getattr(session, "start_talk", None)
            stop_talk = getattr(session, "stop_talk", None)
            if not (send_audio and start_talk and stop_talk):
                raise HomeAssistantError("This camera does not support talk-back")

            ffmpeg = get_ffmpeg_manager(self.hass)
            proc = await asyncio.create_subprocess_exec(
                ffmpeg.binary, "-nostdin", "-i", url,
                "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "8000", "-ac", "1", "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )

            # 960 samples * 2 bytes = 120 ms per chunk at 8 kHz, matching the
            # camera's own audio chunking.
            chunk_bytes = 1920
            chunk_seconds = 0.12
            await start_talk()
            try:
                while True:
                    pcm = await proc.stdout.read(chunk_bytes)
                    if not pcm:
                        break
                    await send_audio(pcm)
                    # Pace by how much audio this chunk actually represents.
                    await asyncio.sleep(chunk_seconds * len(pcm) / chunk_bytes)
            finally:
                await stop_talk()
                if proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        proc.terminate()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(proc.wait(), timeout=5)

    async def async_sync_datetime(self, data=None) -> None:
        """Set the camera clock to Home Assistant's local time."""
        async with self.ensure_connected():
            session = self.device.session
            set_datetime = getattr(session, "set_datetime", None)
            if set_datetime is None:
                raise HomeAssistantError("This camera does not support setting the time")
            # The camera stores the timezone as seconds WEST of UTC; passing
            # the east-positive offset here inverted every sync (UTC+3 became
            # UTC-3). aiopppp>=0.4.0 computes the correct wire value itself
            # when tz_seconds is left unset, so don't second-guess it.
            await set_datetime(dt_util.now())


    @contextlib.asynccontextmanager
    async def ensure_connected(self):
        """Ensure the device is connected."""
        await self.connect()
        try:
            yield self
        finally:
            await self.close()

    async def async_manually_set_date_and_time(self) -> None:
        """Set Date and Time Manually using SetSystemDateAndTime command."""
        pass

        # device_mgmt = await self.device.create_devicemgmt_service()
        #
        # # Retrieve DateTime object from camera to use as template for Set operation
        # device_time = await device_mgmt.GetSystemDateAndTime()
        #
        # system_date = dt_util.utcnow()
        # LOGGER.debug("System date (UTC): %s", system_date)
        #
        # dt_param = device_mgmt.create_type("SetSystemDateAndTime")
        # dt_param.DateTimeType = "Manual"
        # # Retrieve DST setting from system
        # dt_param.DaylightSavings = bool(time.localtime().tm_isdst)
        # dt_param.UTCDateTime = {
        #     "Date": {
        #         "Year": system_date.year,
        #         "Month": system_date.month,
        #         "Day": system_date.day,
        #     },
        #     "Time": {
        #         "Hour": system_date.hour,
        #         "Minute": system_date.minute,
        #         "Second": system_date.second,
        #     },
        # }
        # # Retrieve timezone from system
        # system_timezone = str(system_date.astimezone().tzinfo)
        # timezone_names: list[str | None] = [system_timezone]
        # if (time_zone := device_time.TimeZone) and system_timezone != time_zone.TZ:
        #     timezone_names.append(time_zone.TZ)
        # timezone_names.append(None)
        # timezone_max_idx = len(timezone_names) - 1
        # LOGGER.debug(
        #     "%s: SetSystemDateAndTime: timezone_names:%s", self.name, timezone_names
        # )
        # for idx, timezone_name in enumerate(timezone_names):
        #     dt_param.TimeZone = timezone_name
        #     LOGGER.debug("%s: SetSystemDateAndTime: %s", self.name, dt_param)
        #     try:
        #         await device_mgmt.SetSystemDateAndTime(dt_param)
        #         LOGGER.debug("%s: SetSystemDateAndTime: success", self.name)
        #     # Some cameras don't support setting the timezone and will throw an IndexError
        #     # if we try to set it. If we get an error, try again without the timezone.
        #     except (IndexError, Fault):
        #         if idx == timezone_max_idx:
        #             raise
        #     else:
        #         return

    async def async_check_date_and_time(self) -> None:
        """Warns if device and system date not synced."""

        pass
        # LOGGER.debug("%s: Setting up the ONVIF device management service", self.name)
        # device_mgmt = await self.device.create_devicemgmt_service()
        # system_date = dt_util.utcnow()
        #
        # LOGGER.debug("%s: Retrieving current device date/time", self.name)
        # try:
        #     device_time = await device_mgmt.GetSystemDateAndTime()
        # except RequestError as err:
        #     LOGGER.warning(
        #         "Couldn't get device '%s' date/time. Error: %s", self.name, err
        #     )
        #     return
        #
        # if not device_time:
        #     LOGGER.debug(
        #         """Couldn't get device '%s' date/time.
        #         GetSystemDateAndTime() return null/empty""",
        #         self.name,
        #     )
        #     return
        #
        # LOGGER.debug("%s: Device time: %s", self.name, device_time)
        #
        # tzone = dt_util.get_default_time_zone()
        # cdate = device_time.LocalDateTime
        # if device_time.UTCDateTime:
        #     tzone = dt_util.UTC
        #     cdate = device_time.UTCDateTime
        # elif device_time.TimeZone:
        #     tzone = await dt_util.async_get_time_zone(device_time.TimeZone.TZ) or tzone
        #
        # if cdate is None:
        #     LOGGER.warning("%s: Could not retrieve date/time on this camera", self.name)
        #     return
        #
        # try:
        #     cam_date = dt.datetime(
        #         cdate.Date.Year,
        #         cdate.Date.Month,
        #         cdate.Date.Day,
        #         cdate.Time.Hour,
        #         cdate.Time.Minute,
        #         cdate.Time.Second,
        #         0,
        #         tzone,
        #     )
        # except ValueError as err:
        #     LOGGER.warning(
        #         "%s: Could not parse date/time from camera: %s", self.name, err
        #     )
        #     return
        #
        # cam_date_utc = cam_date.astimezone(dt_util.UTC)
        #
        # LOGGER.debug(
        #     "%s: Device date/time: %s | System date/time: %s",
        #     self.name,
        #     cam_date_utc,
        #     system_date,
        # )
        #
        # dt_diff = cam_date - system_date
        # self._dt_diff_seconds = dt_diff.total_seconds()
        #
        # # It could be off either direction, so we need to check the absolute value
        # if abs(self._dt_diff_seconds) < 5:
        #     return
        #
        # if device_time.DateTimeType != "Manual":
        #     self._async_log_time_out_of_sync(cam_date_utc, system_date)
        #     return
        #
        # # Set Date and Time ourselves if Date and Time is set manually in the camera.
        # try:
        #     await self.async_manually_set_date_and_time()
        # except (RequestError, TransportError, IndexError, Fault):
        #     LOGGER.warning("%s: Could not sync date/time on this camera", self.name)
        #     self._async_log_time_out_of_sync(cam_date_utc, system_date)

    # @callback
    # def _async_log_time_out_of_sync(
    #     self, cam_date_utc: dt.datetime, system_date: dt.datetime
    # ) -> None:
    #     """Log a warning if the camera and system date/time are not synced."""
    #     LOGGER.warning(
    #         (
    #             "The date/time on %s (UTC) is '%s', "
    #             "which is different from the system '%s', "
    #             "this could lead to authentication issues"
    #         ),
    #         self.name,
    #         cam_date_utc,
    #         system_date,
    #     )


    # async def async_perform_ptz(
    #     self,
    #     profile: Profile,
    #     distance,
    #     speed,
    #     move_mode,
    #     continuous_duration,
    #     preset,
    #     pan=None,
    #     tilt=None,
    #     zoom=None,
    # ):
    #     """Perform a PTZ action on the camera."""
    #     if not self.capabilities.ptz:
    #         LOGGER.warning("PTZ actions are not supported on device '%s'", self.name)
    #         return
    #
    #     ptz_service = await self.device.create_ptz_service()
    #
    #     pan_val = distance * PAN_FACTOR.get(pan, 0)
    #     tilt_val = distance * TILT_FACTOR.get(tilt, 0)
    #     zoom_val = distance * ZOOM_FACTOR.get(zoom, 0)
    #     speed_val = speed
    #     preset_val = preset
    #     LOGGER.debug(
    #         (
    #             "Calling %s PTZ | Pan = %4.2f | Tilt = %4.2f | Zoom = %4.2f | Speed ="
    #             " %4.2f | Preset = %s"
    #         ),
    #         move_mode,
    #         pan_val,
    #         tilt_val,
    #         zoom_val,
    #         speed_val,
    #         preset_val,
    #     )
    #     try:
    #         req = ptz_service.create_type(move_mode)
    #         req.ProfileToken = profile.token
    #         if move_mode == CONTINUOUS_MOVE:
    #             # Guard against unsupported operation
    #             if not profile.ptz or not profile.ptz.continuous:
    #                 LOGGER.warning(
    #                     "ContinuousMove not supported on device '%s'", self.name
    #                 )
    #                 return
    #
    #             velocity = {}
    #             if pan is not None or tilt is not None:
    #                 velocity["PanTilt"] = {"x": pan_val, "y": tilt_val}
    #             if zoom is not None:
    #                 velocity["Zoom"] = {"x": zoom_val}
    #
    #             req.Velocity = velocity
    #
    #             await ptz_service.ContinuousMove(req)
    #             await asyncio.sleep(continuous_duration)
    #             req = ptz_service.create_type("Stop")
    #             req.ProfileToken = profile.token
    #             await ptz_service.Stop(
    #                 {"ProfileToken": req.ProfileToken, "PanTilt": True, "Zoom": False}
    #             )
    #         elif move_mode == RELATIVE_MOVE:
    #             # Guard against unsupported operation
    #             if not profile.ptz or not profile.ptz.relative:
    #                 LOGGER.warning(
    #                     "RelativeMove not supported on device '%s'", self.name
    #                 )
    #                 return
    #
    #             req.Translation = {
    #                 "PanTilt": {"x": pan_val, "y": tilt_val},
    #                 "Zoom": {"x": zoom_val},
    #             }
    #             req.Speed = {
    #                 "PanTilt": {"x": speed_val, "y": speed_val},
    #                 "Zoom": {"x": speed_val},
    #             }
    #             await ptz_service.RelativeMove(req)
    #         elif move_mode == ABSOLUTE_MOVE:
    #             # Guard against unsupported operation
    #             if not profile.ptz or not profile.ptz.absolute:
    #                 LOGGER.warning(
    #                     "AbsoluteMove not supported on device '%s'", self.name
    #                 )
    #                 return
    #
    #             req.Position = {
    #                 "PanTilt": {"x": pan_val, "y": tilt_val},
    #                 "Zoom": {"x": zoom_val},
    #             }
    #             req.Speed = {
    #                 "PanTilt": {"x": speed_val, "y": speed_val},
    #                 "Zoom": {"x": speed_val},
    #             }
    #             await ptz_service.AbsoluteMove(req)
    #         elif move_mode == GOTOPRESET_MOVE:
    #             # Guard against unsupported operation
    #             if not profile.ptz or not profile.ptz.presets:
    #                 LOGGER.warning(
    #                     "Absolute Presets not supported on device '%s'", self.name
    #                 )
    #                 return
    #             if preset_val not in profile.ptz.presets:
    #                 LOGGER.warning(
    #                     (
    #                         "PTZ preset '%s' does not exist on device '%s'. Available"
    #                         " Presets: %s"
    #                     ),
    #                     preset_val,
    #                     self.name,
    #                     ", ".join(profile.ptz.presets),
    #                 )
    #                 return
    #
    #             req.PresetToken = preset_val
    #             req.Speed = {
    #                 "PanTilt": {"x": speed_val, "y": speed_val},
    #                 "Zoom": {"x": speed_val},
    #             }
    #             await ptz_service.GotoPreset(req)
    #         elif move_mode == STOP_MOVE:
    #             await ptz_service.Stop(req)
    #     except ONVIFError as err:
    #         if "Bad Request" in err.reason:
    #             LOGGER.warning("Device '%s' doesn't support PTZ", self.name)
    #         else:
    #             LOGGER.error("Error trying to perform PTZ action: %s", err)


def get_device(
    hass: HomeAssistant,
    host: str,
    username: str | None,
    password: str | None,
    on_video_state_change=None,
) -> aiopppp.Device:
    """Get Device instance."""
    return aiopppp.Device(
        host,
        username=username,
        password=password,
        on_video_state_change=on_video_state_change,
    )
