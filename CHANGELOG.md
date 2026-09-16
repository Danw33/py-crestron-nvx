# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses semantic versioning.

## [Unreleased]

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
