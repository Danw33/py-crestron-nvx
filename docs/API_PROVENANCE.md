# API provenance and clean-source policy

This project is an independent implementation of Crestron's publicly
accessible, publicly documented DM NVX REST API:

- [API reference](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/API-Reference.htm)
- [Authentication](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Authentication.htm)

The public reference identifies the HTTPS session procedure, API object paths,
methods, property names, property types, and model-specific applicability. The
implementation is based on those public descriptions plus ordinary
compatibility testing of documented API responses from hardware owned or
administered by contributors.

This repository must not contain copied vendor prose, documentation pages,
sample payloads, diagrams, firmware, decompiled code, credentials, cookies,
private SDK material, or information supplied under confidentiality terms.
Contributors must not submit material they are not entitled to share.

Tests use minimal synthetic payloads with invented identifiers and addresses.
Hardware observations may establish whether documented fields are present,
absent, or represented by a documented primitive type; raw responses and
network captures must remain outside the repository.

Public documentation does not imply that Crestron endorses this project,
guarantees the API, or promises compatibility across releases. The upstream
documentation remains authoritative and should be linked rather than copied.
