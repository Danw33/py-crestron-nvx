# crestron-nvx

[![CI](https://github.com/Danw33/py-crestron-nvx/actions/workflows/ci.yml/badge.svg)](https://github.com/Danw33/py-crestron-nvx/actions/workflows/ci.yml)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FDanw33%2Fpy-crestron-nvx%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)
[![PyPI Version](https://img.shields.io/pypi/v/crestron-nvx)](https://pypi.org/project/crestron-nvx)

An **unofficial** async Python client for direct local communication with
Crestron DM NVX AV-over-IP endpoints.

> [!IMPORTANT]
> This is an independent, unofficial community project. It is not affiliated
> with, endorsed by, sponsored by, or supported by Crestron Electronics, Inc.
> Crestron, DigitalMedia, DM, DM NVX, and related names and marks are trademarks
> or registered trademarks of Crestron Electronics, Inc. in the United States
> and/or other countries. Their use here identifies compatible products only.
> Do not contact Crestron support for help with this library.

## API provenance

This library implements Crestron's **publicly documented DM NVX REST API**.
The authoritative external references are Crestron's public:

- [DM NVX REST API reference](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/API-Reference.htm)
- [DM NVX API authentication guide](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Authentication.htm)

Those references describe the API's HTTPS authentication, GET/POST methods,
object paths, property types, and model-specific applicability. This repository
does not copy or redistribute Crestron manuals, schemas, examples, firmware, or
other proprietary material. The external documentation and device behaviour
may change, and continued compatibility is not guaranteed.

See [API_PROVENANCE.md](docs/API_PROVENANCE.md) for the project's source and
fixture policy.

## Status

Versions through 0.3.0 are read-only. Version 0.4.0 adds
device control. The library authenticates over HTTPS and reads
device identity, device-specific state, A/V I/O status, receive streams, and
transmit streams. An allow-listed read method also supports safe exploration
of documented objects such as Stream Preview Images.

### Capability-driven compatibility (unreleased)

`snapshot.capabilities` exposes an immutable `NvxCapabilities` view derived
from the already-fetched snapshot, with no extra network requests or mutable
capability cache. It centralises source choices, primary stream addressing,
LED support and the documented family-wide reboot operation. Existing snapshot
accessors remain available and delegate to this view.

DM NVX endpoints are recognised by product-family naming, not an exact-model
allowlist. D30, 351, 352, 363 and unfamiliar DM NVX models can use operations
whose required mode, topology and fields are observed. This is best-effort API
compatibility, not a claim of hardware validation for those models. A
receiver-only device without local inputs receives no invented input choices.
Unknown source values and ambiguous stream addressing fail closed.

Capabilities describe support, not current readiness, credentials or guaranteed
write permission. The client still performs fresh identity, automatic-routing,
busy-state, acknowledgement and readback checks. Readable properties do not
automatically become controls: physical control lock remains read-only.
Preview support continues to use the separately fetched `NvxPreviewInfo`.

The [DeviceSpecific API](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Objects/DeviceSpecific.htm)
defines the supported write vocabulary. The API's
[DeviceCapabilities object](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Objects/DeviceCapabilities.htm)
is not a complete writable-feature schema; the library does not treat it as one.
Future controls should extend this shared view with their own documented evidence.

### Explicit LED control

`await client.async_set_leds_enabled(True, expected_device_id=device_id)` returns
a fresh `NvxSnapshot` only after observing the requested state. Pass `False` to
disable LEDs. The optional expected ID is checked against a fresh preflight
read before any write. Only actual booleans are accepted. No writes occur from
constructing a client, monitoring, probing or fetching previews.

The method posts only `LedsEnabled`, checks the acknowledgement and performs
bounded readback. It never replays a POST after a timeout, denial or uncertain
result. An error or cancellation can still mean the device applied the change:
inspect current state before explicitly retrying. Permission failures raise
`NvxPermissionError`; unsupported/read-only controls raise `NvxControlUnsupported`;
other command failures raise `NvxControlError` or existing transport/response
errors. Read permission does not imply write access. No automatic reboot/reset
is implemented.

### Explicit video-source selection

`snapshot.video_source_options` returns documented choices using reported HDMI
slots and mode, without model-specific input limits. Missing, unknown or
unmapped configured source values expose no choices. `None` is the literal API
string, not Python `None`. `Stream` is offered only in receiver mode. Ambiguous
input topology is not guessed from labels; only documented Input1/Input2
mappings are currently implemented.

`await client.async_set_video_source("Input1", expected_device_id=device_id)`
rechecks capabilities and identity before sending only `VideoSource`. It verifies
the configured source, not signal availability or `ActiveVideoSource`. Changes
require `AutoInputRoutingEnabled` to be explicitly false; use the device web UI
to disable automatic input routing first. This method never changes that setting,
stream URLs, device mode or audio source. Selecting the existing supported source
is a no-op. As with LEDs, uncertain outcomes must be reconciled before retrying.
Changing video can interrupt viewing and affect audio that follows video.

Values come from the public [DeviceSpecific reference](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Objects/DeviceSpecific.htm).
Per-device write support still requires supervised hardware validation.

### Explicit reboot

`await client.async_reboot(expected_device_id=device_id)` sends one
`DeviceOperations.Reboot` request after a fresh identity check on a DM NVX
endpoint. The operation can interrupt video and audio until the device returns.
A successful acknowledgement confirms only that
the request was accepted, not that the restart completed. The connection may
close before an acknowledgement; that outcome is uncertain. The client does not
retry, poll for reboot completion, or send `Restore` or `Reset`.

The command is documented in Crestron's public
[DeviceOperations API](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Objects/DeviceOperations.htm).
Reboot has been hardware-tested by the project owner; this does not validate
every model/firmware combination.

### Explicit audio-source selection

`snapshot.audio_source_options` provides conservative choices when the
configured source maps to observed capabilities: Audio Follows Video, observed
HDMI inputs, analog audio when Insert mode is reported, and primary stream
audio on receivers reporting receive streams. Secondary stream audio and NAX
source selection are deferred until their device-specific value mapping is validated.

`await client.async_set_audio_source("Input1", expected_device_id=device_id)`
posts only `AudioSource` and confirms its configured value. It never changes
`ActiveAudioSource`, `NaxAudioSource`, analog mode, video source or routing state.
Manual selection requires `AutoInputRoutingEnabled` to be explicitly false; a
selection of the already configured source is a no-op. An uncertain outcome
requires checking current state before retrying. Changing audio may interrupt
sound or break audio-follows-video behavior. The available values are from the
public [DeviceSpecific reference](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Objects/DeviceSpecific.htm);
hardware write validation remains pending.

`await client.async_get_preview_info()` detects optional preview capability.
`await client.async_get_preview()` returns `NvxPreviewImage` (JPEG bytes and
dimensions), or raises `NvxPreviewUnavailable` when no local image is available.
Other failures use existing typed API exceptions. Unsupported/string-valued
objects are normal on old firmware. No firmware cutoff is assumed.

Only same-origin JPEG paths without redirects are accepted. Responses are
limited to 2 MiB and bounded dimensions, with one authentication retry. Client
operations are serialized to protect the session. Images are not persisted or
logged. Preview display and updates have been validated through Home Assistant
on a firmware 7.1 DM-NVX-360, including remote iOS viewing. Other models and
physical outage/restart recovery remain to be validated.

Version 0.3.0 remains read-only. Version 0.4.0 writes include LEDs, video/audio
source selection, explicit reboot and primary receiver stream URL routing.
Primary stream start/stop commands are also implemented. Device mode writes are
not exposed.

### Primary receiver routing

`await client.async_set_receive_stream_location(location, expected_device_id=identity)`
sets only `StreamReceive.Streams[0].StreamLocation` on an eligible DM NVX receiver.
Pass an advertised, credential-free `rtsp://` URL from a trusted transmitter.
IPv6 literals, URL credentials, queries and fragments are rejected. The client
does not fetch or resolve the stream URL; the receiver uses it. Stream addresses
are private network data: do not log or publish them. They are excluded from
the stream model's repr, but remain present in dataclass serialization.

The operation checks fresh receiver identity and an addressable list-backed
primary slot. A changed URL requires `Processing` false and `SessionInitiation`
`Multicast via RTSP`. One partial POST is followed by bounded configured-state
readback; this is not a guarantee of stream playback. No start/stop, source,
credentials, automatic routing or secondary-slot settings are written. Empty
objects and placeholder slots are never sent. No command is automatically
replayed. After an uncertain failure, inspect the receiver before retrying.

Public references: [StreamReceive](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Objects/StreamReceive.htm),
[StreamTransmit](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Objects/StreamTransmit.htm),
and [partial POST semantics](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Making-API-Calls.htm).
Routing had been validated on a receiving 350 between transmitting 350 and E30
devices in the standalone HA checkpoint. Monitoring compatibility does not imply
that writes have been validated on every supported firmware.

### Explicit primary stream commands

`await client.async_set_stream_running("receive", True, expected_device_id=identity)`
sends a primary receive start command; use `False` to stop. `"transmit"` selects
the transmitter direction. Only the direction matching the reported device
mode is eligible. A primary list-backed slot with status
and explicit non-busy `Processing` is required. Reception start also requires
a valid configured RTSP URL. Transmitter stop can interrupt multiple receivers.

The method posts only `Start: true` or `Stop: true` to slot 0 and checks up to
five readbacks, with a 0.5-second delay between attempts, for non-busy reported
`Stream started`/`Stream stopped` status (case-insensitive). HTTP requests retain
their normal timeouts. It does not infer persistent state from command flags,
skip a requested command based on potentially stale status, automatically replay
a POST, or write any other property. Acknowledgement without matching status is
an uncertain outcome, not success; playback itself is not verified. Hardware
start/stop validation remains pending.

The existing monitoring validation record is:

| Model | Firmware 6.0 | Firmware 7.1 |
| --- | --- | --- |
| DM-NVX-350 | Supported; validation pending | Supported; hardware validated |
| DM-NVX-360 | Supported; validation pending | Supported; hardware validated |
| DM-NVX-E30 | Supported; hardware validated | Supported; validation pending |
| DM-NVX-D30 / 351 / 352 / 363 | Capability-based; hardware validation pending | Capability-based; hardware validation pending |

The parser detects capabilities from returned objects and fields. It does not
reject other firmware versions, but versions outside this table are currently
best-effort.

A DM-NVX-350 on `1.3707.00028` also passed authentication and API-shape probing;
its string-valued Preview response is treated as unsupported.

## Installation

Install the package from PyPI:

```console
python -m pip install crestron-nvx
```

For development:

```console
python -m pip install --editable '.[test]'
```

## Usage

```python
from aiohttp import ClientSession
from crestron_nvx import NvxClient

async with ClientSession() as session:
    client = NvxClient(
        session,
        "192.0.2.10",
        "username",
        "password",
        verify_ssl=False,
    )
    snapshot = await client.async_get_snapshot()
    print(snapshot.device.model)
```

`verify_ssl=False` accepts an endpoint without authenticating its certificate.
This is often necessary for factory/self-signed DM NVX certificates, but an
on-path device could then impersonate the endpoint and receive its credentials.
Use that mode only on a trusted, isolated local network. Prefer
`verify_ssl=True` whenever the endpoint certificate is trusted by the client
host. Never log credentials, authentication cookies, raw device responses, or
personally identifying endpoint data.

## Development

Install the test dependencies and run:

```console
ruff format --check .
ruff check .
mypy
pytest --cov=crestron_nvx --cov-report=term-missing
python -m build
twine check dist/*
```

Tests use small, invented fixtures that describe only the fields required to
exercise library behaviour. Raw device responses must not be committed.

## Licence

Copyright © 2026 Daniel Wilson ([@Danw33](https://github.com/Danw33))

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). 
The licence covers this project's code and documentation; it does not grant rights to third-party
trademarks, firmware, documentation, or other materials.

Crestron and DM NVX are trademarks of their respective owners.
