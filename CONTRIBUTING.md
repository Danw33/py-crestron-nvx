# Contributing

Contributions are welcome when they preserve the library's async, typed, and
device-agnostic API boundary.

Before opening a pull request:

1. Add or update focused tests.
2. Run Ruff formatting and linting, mypy, pytest with coverage, and the package
   build checks documented in the README.
3. Update the changelog for user-visible behaviour.
4. Keep the client independent of Home Assistant and other consumers.

Do not commit raw device responses, packet captures, credentials, cookies,
serial numbers, MAC addresses, stream addresses, user-assigned names, copied
vendor documentation, private SDK content, firmware, or decompiled material.
Use invented values and the smallest payload needed for each test. See
[API_PROVENANCE.md](docs/API_PROVENANCE.md).

Write/control operations require separate review, explicit tests for failure
and authentication behaviour, and documentation of their device-side effects.
