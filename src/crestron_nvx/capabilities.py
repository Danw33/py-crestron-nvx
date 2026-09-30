"""Observed support for documented operations, not a model certification list.

Capabilities describe the current snapshot, not permissions or readiness.
Clients must still perform fresh identity, busy-state and routing checks before
writing. Read-only properties never acquire write support merely by existing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import NvxSnapshot, NvxStream


def is_nvx_model(model: str) -> bool:
    """Recognize the DM NVX product family without enumerating model numbers."""
    return re.fullmatch(r"DM-NVX-[A-Z0-9]+(?:-[A-Z0-9]+)*", model.upper()) is not None


@dataclass(frozen=True, slots=True)
class NvxCapabilities:
    """Immutable support view derived from existing, typed endpoint observations.

    Stream references retain addressing metadata without exposing URLs in repr.
    Reboot is a documented family-wide command, not a readable status flag.
    Preview capability remains in NvxPreviewInfo, fetched only on demand.
    """

    is_nvx: bool = False
    leds_control: bool = False
    reboot: bool = False
    video_source_options: tuple[str, ...] = ()
    audio_source_options: tuple[str, ...] = ()
    receive_routing_stream: NvxStream | None = None
    receive_control_stream: NvxStream | None = None
    transmit_control_stream: NvxStream | None = None

    @classmethod
    def from_snapshot(cls, snapshot: NvxSnapshot) -> NvxCapabilities:
        """Use reported mode and topology; never guess ports from model names."""
        if not is_nvx_model(snapshot.device.model):
            return cls()

        receiver = snapshot.device_mode == "Receiver"
        transmitter = snapshot.device_mode == "Transmitter"
        # Only these two local input values are documented for this operation.
        # Stable list-backed HDMI slots establish the mapping, not display names.
        inputs = tuple(
            f"Input{index + 1}"
            for index in range(2)
            if any(
                port.direction == "input"
                and port.port_id == f"input_slot{index}_hdmi_0"
                for port in snapshot.av_ports
            )
        )
        video: tuple[str, ...] = ()
        audio: tuple[str, ...] = ()
        if receiver or transmitter:
            video_choices = ("None", *inputs, *(("Stream",) if receiver else ()))
            if snapshot.video_source in video_choices:
                video = video_choices
            audio_choices = (
                "AudioFollowsVideo",
                *inputs,
                *(("AnalogAudio",) if snapshot.audio_mode == "Insert" else ()),
                *(
                    ("PrimaryStreamAudio",)
                    if receiver and snapshot.receive_streams
                    else ()
                ),
            )
            if snapshot.audio_source in audio_choices:
                audio = audio_choices

        receive = (
            _primary_stream(snapshot.receive_streams, "receive") if receiver else None
        )
        transmit = (
            _primary_stream(snapshot.transmit_streams, "transmit")
            if transmitter
            else None
        )
        return cls(
            is_nvx=True,
            leds_control=snapshot.leds_enabled is not None,
            reboot=True,
            video_source_options=video,
            audio_source_options=audio,
            receive_routing_stream=(
                receive
                if receive is not None and receive.stream_location is not None
                else None
            ),
            receive_control_stream=_control_stream(receive),
            transmit_control_stream=_control_stream(transmit),
        )


def _primary_stream(streams: tuple[NvxStream, ...], direction: str) -> NvxStream | None:
    """Require a single unambiguous, list-addressable primary slot."""
    candidates = tuple(
        stream
        for stream in streams
        if stream.slot_index == 0 and stream.direction == direction
    )
    return candidates[0] if len(candidates) == 1 else None


def _control_stream(stream: NvxStream | None) -> NvxStream | None:
    """Presence establishes support; the client checks current busy state."""
    if (
        stream is not None
        and stream.processing is not None
        and stream.status is not None
    ):
        return stream
    return None
