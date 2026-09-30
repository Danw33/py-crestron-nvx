# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses semantic versioning.

## [Unreleased]

### Added

- Explicit video-source selection with model/topology/mode-filtered options,
  identity checks, configured-state readback and no automatic write replay.
  Source changes require automatic input routing to be explicitly off; no
  routing automation, audio, mode or stream addressing is changed.

- Explicit LED-only control with strict boolean input, optional expected-device
  identity verification, fresh preflight/readback and serialized endpoint I/O.
- Typed control, unsupported/read-only and permission errors. Writes are never
  automatically replayed; uncertain outcomes must be reconciled by reading.
- Fixed nonempty partial payloads and bounded, relevant acknowledgement checks.

## [0.3.0]

### Fixed

- Use physical slot/type keys for A/V ports instead of UUIDs that firmware 7.1
  regenerates on every response. Standard input/output slot designators survive
  group reordering and HDMI display-name changes.

### Changed

- `NvxStream.bitrate_mbps` now contains only the reported `Bitrate` value.
  Consumers needing the active transmit measurement must use the new optional
  `active_bitrate_mbps` field. Missing active readings remain `None`.
- Port IDs change from API UUIDs to physical keys. Consumers that persist these
  IDs need a migration; see `docs/TELEMETRY.md` for identity limitations.

## [0.2.0]

### Added

- Accept case-insensitive local preview hosting values observed on firmware 7.1.
- Prefer available images by descending pixel area, retaining path validation
  and download limits; unknown dimensions sort last with stable tie ordering.

- Typed optional preview capability and authenticated JPEG retrieval.
- Same-origin paths, redirect rejection, bounded image size/dimensions.
- Serialized operations, one authentication retry, and preview regression tests.
- Firmware 1.3707.00028 DM-NVX-350 API-shape evidence; HA validation pending.
- DM-NVX-360 firmware 7.1 preview display and updates validated through HA,
  including Media and remote iOS viewing; other hardware checks remain pending.

### Changed

- Update installation wording following the first PyPI release and correct a
  formatting error in the API provenance statement.

## [0.1.0] - 2026-09-13

### Added

- Initial read-only async client and typed immutable snapshot models.
- HTTPS authentication with isolated cookie handling and one reauthentication
  attempt after session expiry.
- Field-driven parsing for DM-NVX-350, DM-NVX-360, and DM-NVX-E30 devices on
  the declared firmware 6.0 and 7.1 support baseline.
- Synthetic tests, strict typing, linting, coverage enforcement, packaging, and
  trusted-publishing workflow.
- Bounded JSON response reads and endpoint-controlled collections.
- Complete source distribution with tests and project documentation.

### Security

- Keep the authentication bootstrap on the configured endpoint by disabling
  automatic HTTP redirects.
- Document the credential-interception risk when callers disable certificate
  verification for self-signed endpoints.
