"""Typed data models for Crestron DM NVX."""

from dataclasses import dataclass, field
from typing import Any


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
    def primary_receive_stream(self) -> NvxStream | None:
        """Return an explicitly addressable primary slot on supported receivers."""
        if (
            self.device.model.upper() not in {"DM-NVX-350", "DM-NVX-360"}
            or self.device_mode != "Receiver"
        ):
            return None
        return next(
            (
                stream
                for stream in self.receive_streams
                if stream.slot_index == 0 and stream.stream_location is not None
            ),
            None,
        )

    @property
    def video_source_options(self) -> tuple[str, ...]:
        """Conservative choices for known hardware with observed HDMI topology."""
        limits = {"DM-NVX-350": 2, "DM-NVX-360": 1, "DM-NVX-E30": 1}
        limit = limits.get(self.device.model.upper())
        if (
            limit is None
            or self.video_source not in {"None", "Input1", "Input2", "Stream"}
            or self.device_mode not in {"Transmitter", "Receiver"}
            or (
                self.device.model.upper() == "DM-NVX-E30"
                and self.device_mode != "Transmitter"
            )
        ):
            return ()
        choices = ["None"]
        for index in range(limit):
            if any(
                port.direction == "input"
                and port.port_id == f"input_slot{index}_hdmi_0"
                for port in self.av_ports
            ):
                choices.append(f"Input{index + 1}")
        if self.device_mode == "Receiver":
            choices.append("Stream")
        return tuple(choices)

    @property
    def audio_source_options(self) -> tuple[str, ...]:
        """Offer documented primary audio sources for known endpoint topology."""
        limits = {"DM-NVX-350": 2, "DM-NVX-360": 1, "DM-NVX-E30": 1}
        model = self.device.model.upper()
        limit = limits.get(model)
        if (
            limit is None
            or self.audio_source
            not in {
                "AudioFollowsVideo",
                "Input1",
                "Input2",
                "AnalogAudio",
                "PrimaryStreamAudio",
                "SecondaryStreamAudio",
            }
            or self.device_mode not in {"Transmitter", "Receiver"}
            or (model == "DM-NVX-E30" and self.device_mode != "Transmitter")
        ):
            return ()
        choices = ["AudioFollowsVideo"]
        for index in range(limit):
            if any(
                port.direction == "input"
                and port.port_id == f"input_slot{index}_hdmi_0"
                for port in self.av_ports
            ):
                choices.append(f"Input{index + 1}")
        if model != "DM-NVX-E30" and self.audio_mode == "Insert":
            choices.append("AnalogAudio")
        if (
            model != "DM-NVX-E30"
            and self.device_mode == "Receiver"
            and self.receive_streams
        ):
            choices.append("PrimaryStreamAudio")
        return tuple(choices) if self.audio_source in choices else ()
