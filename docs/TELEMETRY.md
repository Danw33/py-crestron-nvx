# Telemetry identity and bitrate semantics (0.3.0)

Port UUIDs on tested DM-NVX-360 firmware 7.1 change with each response. Both group
and port UUIDs are therefore excluded from persistent physical-port identity.
The stable device identity remains the authenticated REST device ID.

Port keys combine direction, a unique machine slot designator (`input0`,
`output0`, etc.), port type, and occurrence within that type. HDMI display names
are labels only. Standard slot groups and different port types may reorder
without changing these keys. Older or malformed shapes without unique machine
slot designators use group position; unknown port types use port position.
Multiple ports of the same type use their relative order. Firmware that changes
these fallback layouts needs validation: arbitrary topology changes cannot be
resolved from these responses alone. The algorithm does not claim to identify
removable or dynamically rearranged ports.

This changes persisted `NvxAvPort.port_id` values. HA migrates only recognised,
unambiguously labelled legacy registry entries and retains historical duplicates
for manual review. Other consumers should plan their own migration.

`NvxStream.bitrate_mbps` now means the API's `Bitrate` value exclusively.
`active_bitrate_mbps` separately contains transmit `ActiveBitrate`, or `None`
when absent/invalid. No fallback, scaling, status-based zeroing or clamping is
performed. Explicit zero and missing data remain different. Receive streams
have no active transmit measurement.

The [public StreamTransmit API reference](https://sdkcon78221.crestron.com/sdk/DM_NVX_REST_API/Content/Topics/Objects/StreamTransmit.htm)
documents the two bitrate fields separately. Tested firmware can report
apparently default values on unused slots and false readiness on functioning
devices. The library preserves these observations; it does not infer operational
health or stream capability from readiness, counters or status alone.
