"""Typed data models for Crestron DM NVX."""

from dataclasses import dataclass, field
from typing import Any

from .capabilities import NvxCapabilities


@dataclass(frozen=True, slots=True)
class NvxDeviceInfo:
    """Identity data returned by the endpoint."""

    device_id: str
    name: str
    model: str
    serial_number: str | None = None
    firmware_version: str | None = None
    mac_address: str | None = None
    manufacturer: str = "Crestron"
    reboot_reason: str | None = None


@dataclass(frozen=True, slots=True)
class NvxAvPort:
    """Physical A/V port status, keyed by topology rather than transient UUID."""

    port_id: str
    name: str
    direction: str
    sync_detected: bool | None = None
    sink_connected: bool | None = None
    transmitting: bool | None = None
    hdcp_state: str | None = None
    horizontal_resolution: int | None = None
    vertical_resolution: int | None = None
    frames_per_second: int | None = None

    @property
    def resolution(self) -> str | None:
        """Return a compact resolution string."""

        if not self.horizontal_resolution or not self.vertical_resolution:
            return None
        resolution = f"{self.horizontal_resolution}x{self.vertical_resolution}"
        if self.frames_per_second is not None:
            return f"{resolution}@{self.frames_per_second}"
        return resolution


@dataclass(frozen=True, slots=True)
class NvxStream:
    """Read-only status for one receive or transmit stream slot."""

    stream_id: str
    direction: str
    status: str | None = None
    codec_ready: bool | None = None
    bitrate_mbps: int | None = None  # Raw Bitrate; not an active-rate fallback.
    horizontal_resolution: int | None = None
    vertical_resolution: int | None = None
    frames_per_second: int | None = None
    # Bitrate is the raw reported field; ActiveBitrate is a separate measurement.
    # Absence must not be replaced with Bitrate or inferred from stream status.
    active_bitrate_mbps: int | None = None
    # Only list-backed slots are addressable; never infer an index from a UUID.
    slot_index: int | None = None
    stream_location: str | None = field(default=None, repr=False)
    processing: bool | None = None
    session_initiation: str | None = None

    @property
    def resolution(self) -> str | None:
        """Return a compact stream resolution string."""

        if not self.horizontal_resolution or not self.vertical_resolution:
            return None
        resolution = f"{self.horizontal_resolution}x{self.vertical_resolution}"
        if self.frames_per_second is not None:
            return f"{resolution}@{self.frames_per_second}"
        return resolution


@dataclass(frozen=True, slots=True)
class NvxSnapshot:
    """One immutable, read-only endpoint snapshot."""

    device: NvxDeviceInfo
    device_mode: str | None = None
    device_ready: bool | None = None
    active_audio_source: str | None = None
    active_video_source: str | None = None
    audio_mode: str | None = None
    audio_source: str | None = None
    video_source: str | None = None
    nax_active_audio_source: str | None = None
    nax_audio_source: str | None = None
    auto_initiation_mode: bool | None = None
    auto_input_routing_enabled: bool | None = None
    front_panel_lockout_enabled: bool | None = None
    leds_enabled: bool | None = None
    show_setup_information_on_osd: bool | None = None
    av_ports: tuple[NvxAvPort, ...] = ()
    receive_streams: tuple[NvxStream, ...] = ()
    transmit_streams: tuple[NvxStream, ...] = ()
    raw_device_specific: dict[str, Any] = field(default_factory=dict)

    @property
    def capabilities(self) -> NvxCapabilities:
        """Derive supported operations without I/O or a separate mutable cache."""
        return NvxCapabilities.from_snapshot(self)

    def primary_control_stream(self, direction: str) -> NvxStream | None:
        """Compatibility accessor for the matching active-direction stream."""
        if direction == "receive":
            return self.capabilities.receive_control_stream
        if direction == "transmit":
            return self.capabilities.transmit_control_stream
        return None

    @property
    def primary_receive_stream(self) -> NvxStream | None:
        """Compatibility accessor for an addressable receiver routing slot."""
        return self.capabilities.receive_routing_stream

    @property
    def video_source_options(self) -> tuple[str, ...]:
        """Compatibility accessor for documented, observed video choices."""
        return self.capabilities.video_source_options

    @property
    def audio_source_options(self) -> tuple[str, ...]:
        """Compatibility accessor for documented, observed audio choices."""
        return self.capabilities.audio_source_options
