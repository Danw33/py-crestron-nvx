"""Minimal clock capability metadata; never retain server addresses or secrets."""

import re
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NvxClockInfo:
    """Support is separate from current readiness; no sync-success inference."""

    sync_supported: bool = False
    enabled: bool | None = None
    has_server: bool = False

    @property
    def can_sync(self) -> bool:
        return self.sync_supported and self.enabled is True and self.has_server


def parse_clock(payload: Mapping[str, object]) -> NvxClockInfo:
    """Recognize documented Ntp schema, not deprecated/undocumented Sntp writes."""
    device = payload.get("Device")
    clock = device.get("SystemClock") if isinstance(device, Mapping) else None
    if not isinstance(clock, Mapping):
        return NvxClockInfo()
    version = clock.get("Version")
    ntp = clock.get("Ntp")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return NvxClockInfo()
    if tuple(map(int, version.split("."))) < (2, 1, 0) or not isinstance(ntp, Mapping):
        return NvxClockInfo()
    enabled = ntp.get("IsEnabled")
    # Firmware may encode bools as 0/1; do not use truthiness of arbitrary strings.
    if type(enabled) is int and enabled in (0, 1):
        enabled = bool(enabled)
    servers = ntp.get("Servers")
    has_server = isinstance(servers, Mapping) and any(
        isinstance(entry, Mapping)
        and isinstance(entry.get("Address"), str)
        and bool(entry["Address"].strip())
        for entry in servers.values()
    )
    return NvxClockInfo(True, enabled if type(enabled) is bool else None, has_server)
