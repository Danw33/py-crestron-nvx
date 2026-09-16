# pycrestron-nvx

[![CI](https://github.com/Danw33/py-crestron-nvx/actions/workflows/ci.yml/badge.svg)](https://github.com/Danw33/py-crestron-nvx/actions/workflows/ci.yml)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

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

This library implements Crestron's ** publicly documented DM NVX REST API**. 
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

Version 0.1 is deliberately read-only. It authenticates over HTTPS and reads
device identity, device-specific state, A/V I/O status, receive streams, and
transmit streams. An allow-listed read method also supports safe exploration
of documented objects such as Preview.

No reboot, routing, input, mode, stream, or configuration write can be issued
by this release.

The declared initial support scope is:

| Model | Firmware 6.0 | Firmware 7.1 |
| --- | --- | --- |
| DM-NVX-350 | Supported; validation pending | Supported; hardware validated |
| DM-NVX-360 | Supported; validation pending | Supported; hardware validated |
| DM-NVX-E30 | Supported; hardware validated | Supported; validation pending |

The parser detects capabilities from returned objects and fields. It does not
reject other firmware versions, but versions outside this table are currently
best-effort.

## Installation

The package will be installable after its first PyPI release:

```console
python -m pip install pycrestron-nvx
```

For development before that release:

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
