# PPPP Camera Component for Home Assistant

## Overview

The `pppp camera` component allows Home Assistant to connect and integrate cheap Wi-Fi cameras such as **A9, X5**, and similar models using the **aiopppp** library. 
These cameras typically use the **Peer-to-Peer protocol** for communication, and this component enables live-streaming and snapshot capture within Home Assistant.

## Features

- Supports A9, X5, and similar PPPP protocol cameras, over **both the JSON and
  the binary control protocol** (binary is currently the better-tested path)
- Live streaming via aiopppp
- Snapshot support
- PTZ control through actions/services, including preset slots
- White lights and IR lights control
- **Talk-back**: play a media or TTS source through the camera speaker
- Video resolution as a config entity (dropdown) — see
  [Known issues](#known-issues)
- Diagnostic sensors: battery, power source, Wi-Fi signal, SD card usage,
  Wi-Fi network, camera clock offset and timezone
- Camera clock sync button
- On-demand connections — the camera is only held open while something needs
  it, because these cameras accept **one client at a time**
- Automatic reconnection with backoff when a camera drops off the network
- Support for webrtc custom component
- Automatic device discovery, probing with both the plain and the extended
  PPPP search packet — some firmwares only answer the extended one
- (TBD) Listening to camera audio in Home Assistant — the library supports it,
  but the HA camera entity streams video only

## Tested camera prefixes

| Prefix   | Protocol | Video | Snapshot | PTZ | White Light | IR Light | Reboot | Resolution | Talk | Time sync |
|:---------|:---------|:-----:|:--------:|:---:|:-----------:|:--------:|:------:|:----------:|:----:|:---------:|
| **DGOK** | 📜 JSON  | ✅   | ✅      | ✅  | ✅          | ✅      | ✅     | ✖️        | ✖️  | ✖️       |
| **PTZA** | 🔢 Binary| ✅   | ✅      | ✅  | ✅          | 🚫      | ✅     | ✅        | ✅  | ✅       |
| **FTYC** | 🔢 Binary| ✅   | ✅      | 🚫  | 🚫          | ✅      | ✅     | ✅        | 🚫  | ⚠️       |
| [**BATE**<sup>*</sup>](https://github.com/devbis/pppp_camera/issues/4) | 🔢 Binary|❔ |❔ | ❔   | ❔           | ❔       | ❔     |  ❔        | ❔  | ❔       |
| [**DGB**<sup>*</sup>](https://github.com/devbis/pppp_camera/issues/2) | 📜 JSON   |⚠️ |❔ | ❔   | ❔           | ❔       | ❔     |  ❔        | ✖️  | ✖️       |
| [**ACCQ**<sup>*</sup>](https://github.com/devbis/pppp_camera/issues/1) | ❔ Unknown|✖️|✖️ | ✖️  | ✖️          | ✖️      | ✖️     | ✖️        | ✖️  | ✖️       |

**Legend:**
- &nbsp;✅&nbsp; **Working**: Feature is fully functional.
- &thinsp;⚠️&thinsp;**Partially working**: Feature works with limitations or issues.
- &nbsp;❌&nbsp; **Not working**: Feature is implemented but does not function.
- &nbsp;✖️&nbsp; **Not implemented**: Feature is not implemented in the system.
- &nbsp;🚫&nbsp; **Not supported**: Feature is not supported by the device.
- &ensp;❔ &nbsp; **Not tested**: Feature has not been tested on the device.

Notes: FTYC has no speaker, so talk-back cannot be tested there. FTYC time
sync sets the clock but has no timezone field to write, so its UTC offset
stays whatever the vendor app configured. JSON cameras expose no set-time
command. PTZ presets are sent using the scheme found in the vendor app, but
none of the tested cameras act on them — see
[services](#services) below.

> **Status:** the capability matrix above is what the underlying `aiopppp`
> library was verified to do against real cameras. The Home Assistant side —
> camera, lamps, buttons, diagnostic sensors, resolution select, clock sync,
> talk-back, the services, discovery and the config/options flows — has now
> been exercised in a running Home Assistant against PTZA and FTYC cameras.
> The only entity still unverified is **SD card usage**, for want of a card.

## Known issues

- **A resolution chosen while the camera is idle is overwritten with HD when
  the stream starts.** The library sets HD at stream start and deliberately
  re-asserts it a few seconds in (the cameras otherwise self-downgrade and
  ignore the value set at start time), so an idle selection never survives.
  Set the resolution *while the stream is running* and it sticks. Note the
  same re-request path runs after a video stall, so a mid-stream stall can
  also revert the resolution to HD.

  Fixing it means teaching the library to prefer a chosen resolution instead
  of the hardcoded default, and having the integration re-apply that choice
  on connect so it survives the idle session teardown. Not implemented yet.

## Entities

One device is created per camera. Which entities appear depends on what the
camera actually reports, so a mains-powered camera gets no battery sensor and a
camera without an SD card gets no usage sensor.

| Entity | Platform | Notes |
|:-------|:---------|:------|
| Camera | `camera` | Live stream, snapshots, and turn on/off (starts and stops the video stream) |
| White Lamp / IR Lamp | `switch`, `light` or `button` | Only for cameras reporting that lamp. The platform is chosen by the `platform.lamp` option. Cameras that report real lamp state (function bitmap in the status block) track it live, so changes made from the vendor app show up; the rest assume their own writes |
| Reboot | `button` | Only when logged in — the camera refuses it otherwise |
| Sync time | `button` | Binary-protocol cameras only |
| Resolution | `select` | Binary-protocol cameras only. QVGA / VGA / HD / FD / UD |
| Battery | `sensor` | Only when the camera reports a real battery voltage |
| Power source | `sensor` | External or Battery. Only alongside a battery reading — mains-only cameras leave the field unpopulated rather than reporting "external" |
| Clock offset | `sensor` | Seconds the camera clock is ahead (+) or behind (−) Home Assistant, with the raw camera time as an attribute |
| Wi-Fi network | `sensor` | SSID the camera is joined to |
| Timezone | `sensor` | Disabled by default. Not created for firmwares that don't store one |
| Signal strength | `sensor` | Wi-Fi RSSI in dBm. Disabled by default. Not created when the firmware reports no usable value |
| SD card usage | `sensor` | Disabled by default. Only when a card is present |
| Device type | `sensor` | Disabled by default. Model and chip, e.g. `XR_PTZ (chip 2)` — the same string as the device's Model, with `devType`/`devTypeName`/`chipType`/`chipTypeName` as attributes |

All sensors are diagnostic entities; the resolution select and the reboot/sync
buttons are config entities.

### Polling

These cameras push nothing, and only one client may be connected at a time, so
values are refreshed by briefly opening a session on a timer. Polling is
**demand-driven**: a group of values is only fetched while at least one enabled
entity actually uses it.

| Group | Values | Default interval |
|:------|:-------|:-----------------|
| Status | Battery, power source, signal strength, SD usage | 300 s |
| Info | Camera clock offset, Wi-Fi SSID | 3600 s |

So a camera with no battery and no SD card is never status-polled, and
disabling those entities stops the polling too. Set either interval to `0` to
disable it outright. The timezone sensor never triggers a poll of its own — it
rides along on the clock response, which already carries it.

## Services

| Service | Description |
|:--------|:------------|
| `pppp_camera.ptz` | Pan (`LEFT`/`RIGHT`) or tilt (`UP`/`DOWN`) the camera |
| `pppp_camera.ptz_preset` | Move to (`goto`) or store (`set`) a preset slot, 0–255. Implemented from the vendor app, but **no tested camera acts on it** |
| `pppp_camera.reboot` | Reboot the camera |
| `pppp_camera.talk` | Play an audio media or TTS source through the camera speaker |

## Installation

### Prerequisites

- Home Assistant installed and running. Tested on version 2025.2

### Installation
1. HACS > Integrations > Custom Repositories
2. Add `devbis/pppp_camera` URL.
3. Select **Integration** as the category.

Or manually copy pppp_camera folder to custom_components folder in your config folder.

## Configuration

### Basic Configuration

Add cameras through Home Assistant's **Devices & Services** interface by camera IP address. 
If username and passwords are blank, it will use default values for authentication: `admin:6666`.

Per-camera settings (connection and polling behaviour) are available afterwards
via **Configure** on the integration entry, and override the YAML defaults
below.

### Advanced YAML Configuration (Optional)

For advanced configuration options, you can add the following to your `configuration.yaml` file:

```yaml
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
  idle_disconnect_delay: 5    # seconds to keep a session warm after the last operation
  status_poll_interval: 300   # seconds between battery/signal/SD refreshes
  info_poll_interval: 3600    # seconds between clock/SSID refreshes
```

### Configuration Parameters

#### `defaults` (optional)
Default credentials used for all cameras when not specified during UI setup.

- **`username`** (string, default: `admin`): Default username for camera authentication
- **`password`** (string, default: `6666`): Default password for camera authentication

#### `platform` (optional)
Configure how certain entities are represented in Home Assistant.

- **`lamp`** (string, default: `switch`): Platform type for lamp entities
  - `switch`: Lamps appear as switch entities
  - `light`: Lamps appear as light entities  
  - `button`: Lamps appear as button entities

#### `discovery` (optional)
Configure automatic device discovery on your network.

- **`enabled`** (boolean, default: `true`): Enable or disable automatic discovery
- **`duration`** (integer, default: `10`): Time in seconds to listen for devices during each discovery cycle
- **`interval`** (integer, default: `600`): Time in seconds between discovery attempts (600 = 10 minutes)
- **`ip`** (string or list, optional): Limit discovery to specific IP addresses
  - Can be a single IP address (e.g., `192.168.1.255` for broadcast)
  - Can be a list of specific IP addresses
  - If not specified, discovery listens on all available network interfaces

#### `idle_disconnect_delay` (optional)

- **`idle_disconnect_delay`** (integer, default: `5`): Seconds to keep a camera
  session open after the last in-flight operation completes. These cameras allow
  only one client at a time, so the session is opened on demand and released when
  idle. Keeping it warm briefly lets back-to-back commands (e.g. PTZ bursts) reuse
  the session and prevents a fire-and-forget command from being cut off by an
  immediate disconnect. Set to `0` to disconnect immediately after each operation.

#### `status_poll_interval` (optional)

- **`status_poll_interval`** (integer, default: `300`): Seconds between refreshes
  of battery, power source, signal strength and SD card usage. Only polled while at least
  one of those entities is enabled, so a camera without a battery or SD card is
  never contacted for them. Set to `0` to disable.

#### `info_poll_interval` (optional)

- **`info_poll_interval`** (integer, default: `3600`): Seconds between refreshes
  of the camera clock and Wi-Fi network. These barely change — the SSID only when
  the camera is re-provisioned — so this is deliberately much slower than the
  status poll. Set to `0` to disable.

All four of the above can also be set per camera from the integration's
**Configure** dialog, which takes precedence over the YAML values.

## Usage

- Once configured, the camera feed should be visible in Home Assistant under **Devices & Services**.
- You can view the stream in **Lovelace UI** by adding a picture entity or a camera card.
- Automations can trigger recordings or snapshots.

PTZ control is available through services e.g.:

```yaml 
action: pppp_camera.ptz
data:
  pan: LEFT
target:
  entity_id: camera.dgok_123456_xxxxx
```

Talk-back plays any media or TTS source through the camera speaker:

```yaml
action: pppp_camera.talk
data:
  media:
    media_content_id: media-source://tts/tts.google_en_com?message=Someone+is+at+the+door
    media_content_type: provider
target:
  entity_id: camera.ptza_123456_xxxxx
```

The easiest way to try it is **Developer tools → Actions → Talk**, picking a
short file with the media browser (anything ffmpeg can decode works; it is
transcoded to the 8 kHz mono the camera expects). Note that the action runs for
as long as the audio lasts — it is streamed to the camera in real time — so
test with a few seconds of audio rather than a full song. The camera must
actually have a speaker; not all models do.

## WebRTC component configuration example:

Component project page: https://github.com/AlexxIT/WebRTC

```yaml
type: custom:webrtc-camera
entity: camera.dgok_123456_xxxxx
media: video
ptz:
  service: pppp_camera.ptz
  data_left:
    pan: LEFT
    entity_id: camera.dgok_123456_xxxxx
  data_right:
    pan: RIGHT
    entity_id: camera.dgok_123456_xxxxx
  data_up:
    tilt: UP
    entity_id: camera.dgok_123456_xxxxx
  data_down:
    tilt: DOWN
    entity_id: camera.dgok_123456_xxxxx

shortcuts:
  - name: White Light
    icon: mdi:lightbulb-on
    service: switch.toggle
    service_data:
      entity_id: switch.dgok_123456_xxxxx_white_lamp
  - name: IR lamp
    icon: mdi:weather-night
    service: switch.toggle
    service_data:
      entity_id: switch.dgok_123456_xxxxx_ir_lamp
```

## Troubleshooting

- **Camera not connecting?** Ensure IP is correct and phone application is not connected. Only one client can connect.
- **No video stream?** Sometimes camera doesn't start streaming. Reboot it.  
- **Resolution shows as unknown?** The camera only reports its real video
  parameters while it is streaming; an idle camera answers with an empty table.
  Start the stream and the value fills in a couple of seconds later.
- **Resolution keeps reverting to HD?** Known limitation — set it while the
  stream is running. See [Known issues](#known-issues).
- **Clock offset looks stale after pressing Sync time?** The value is re-read a
  moment after the write. If that read-back doesn't land, the next info poll
  replaces it with a genuine reading.
- **Missing sensors?** Most are conditional (see [Entities](#entities)), and
  signal / SD usage / timezone are disabled by default — enable them
  from the device page.
- **Talk-back does nothing?** The action now fails loudly with ffmpeg's own
  error when the media can't be decoded. If it reports that the URL could not
  be fetched, check that Home Assistant's internal URL is reachable from
  itself, since the audio is pulled back over HTTP before being transcoded.

## Contributing

Contributions are welcome! Feel free to submit issues or pull requests to improve the integration.

## License

This project is licensed under the MIT License.
