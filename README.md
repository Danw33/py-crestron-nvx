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

Published versions through 0.3.0 are read-only. The upcoming 0.4.0 release adds
device control. The library authenticates over HTTPS and reads
device identity, device-specific state, A/V I/O status, receive streams, and
transmit streams. An allow-listed read method also supports safe exploration
of documented objects such as Stream Preview Images.

### Explicit LED control (unreleased)

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

### Explicit video-source selection (unreleased)

`snapshot.video_source_options` returns conservative choices for DM-NVX-350,
DM-NVX-360 and DM-NVX-E30 using model limits, reported HDMI slots and mode.
Unknown hardware or missing/unknown source values expose no choices. `None`
is the literal API string, not Python `None`. `Stream` is offered only in receiver
mode; E30 never offers it. Ambiguous input topology is not guessed from labels.

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

### Explicit audio-source selection (unreleased)

`snapshot.audio_source_options` provides conservative choices for supported
models when the configured source is recognized: Audio Follows Video, observed
HDMI inputs, analog audio in Insert mode on 350/360, and primary stream audio on
350/360 receivers reporting receive streams. The E30 exposes Audio Follows Video
and its observed HDMI input. Secondary stream audio and NAX source selection are
deferred until their device-specific value mapping is validated.

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

Published 0.3.0 remains read-only. Development writes are limited to LEDs and
configured video source; no reboot, network-stream routing or mode writes exist.

The declared initial support scope is:

| Model | Firmware 6.0 | Firmware 7.1 |
| --- | --- | --- |
| DM-NVX-350 | Supported; validation pending | Supported; hardware validated |
| DM-NVX-360 | Supported; validation pending | Supported; hardware validated |
| DM-NVX-E30 | Supported; hardware validated | Supported; validation pending |

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
