"""Capabilities depend on observed API shape, never an exact-model allowlist."""

from dataclasses import FrozenInstanceError, replace

import pytest

from crestron_nvx import NvxAvPort, NvxCapabilities, is_nvx_model

from .test_client import _response
from .test_control import BEFORE, ack, control_client
from .test_stream_control import snapshot


@pytest.mark.parametrize(
    "model",
    [
        "DM-NVX-350",
        "DM-NVX-360",
        "DM-NVX-E30",
        "DM-NVX-D30",
        "DM-NVX-351",
        "DM-NVX-352",
        "DM-NVX-363",
        "DM-NVX-FUTURE",
        "dm-nvx-d30",
        "DM-NVX-350C",
    ],
)
def test_family_model_does_not_determine_features(model):
    base = snapshot()
    base = replace(
        base,
        device=replace(base.device, model=model),
        video_source="Stream",
        audio_source="PrimaryStreamAudio",
    )
    caps = base.capabilities
    assert caps.is_nvx and caps.reboot and caps.leds_control
    assert caps.video_source_options == ("None", "Stream")
    assert caps.audio_source_options == ("AudioFollowsVideo", "PrimaryStreamAudio")
    assert caps.receive_control_stream == base.receive_streams[0]
    assert caps.receive_routing_stream == base.receive_streams[0]
    assert caps.transmit_control_stream is None
    assert base.primary_control_stream("receive") == caps.receive_control_stream
    assert base.primary_receive_stream == caps.receive_routing_stream
    assert base.video_source_options == caps.video_source_options
    assert base.audio_source_options == caps.audio_source_options


@pytest.mark.parametrize("model", ["", "OTHER", "DM-NVX-", "DM-NVX-350\n", "CP4"])
def test_non_nvx_not_advertised_as_writable(model):
    assert not is_nvx_model(model)
    base = replace(BEFORE, device=replace(BEFORE.device, model=model))
    assert base.capabilities == NvxCapabilities()


@pytest.mark.parametrize(
    "model,count",
    [
        ("DM-NVX-350", 2),
        ("DM-NVX-360", 1),
        ("DM-NVX-E30", 1),
    ],
)
def test_observed_hdmi_topology_preserves_existing_choices(model, count):
    base = replace(
        BEFORE,
        device=replace(BEFORE.device, model=model),
        device_mode="Transmitter",
        video_source="None",
        audio_source="AudioFollowsVideo",
        av_ports=tuple(
            NvxAvPort(f"input_slot{i}_hdmi_0", "irrelevant", "input")
            for i in range(count)
        ),
    )
    inputs = tuple(f"Input{i + 1}" for i in range(count))
    assert base.video_source_options == ("None", *inputs)
    assert base.audio_source_options == ("AudioFollowsVideo", *inputs)
    assert base.capabilities.receive_routing_stream is None


def test_missing_unknown_and_read_only_fields_do_not_enable_controls():
    base = replace(
        BEFORE,
        leds_enabled=None,
        front_panel_lockout_enabled=True,
        device_mode="FutureMode",
        video_source="Input3",
        audio_source="Future",
    )
    caps = base.capabilities
    assert not caps.leds_control
    assert caps.video_source_options == caps.audio_source_options == ()
    assert caps.receive_control_stream is caps.transmit_control_stream is None
    assert caps.receive_routing_stream is None
    assert not hasattr(caps, "front_panel_lockout_control")
    with pytest.raises(FrozenInstanceError):
        caps.reboot = False


def test_ambiguous_wrong_direction_and_unaddressable_streams():
    base = snapshot()
    stream = base.receive_streams[0]
    for streams in (
        (),
        (stream, stream),
        (replace(stream, direction="transmit"),),
        (replace(stream, slot_index=None),),
    ):
        caps = replace(base, receive_streams=streams).capabilities
        assert caps.receive_routing_stream is caps.receive_control_stream is None
    for field in ("processing", "status"):
        caps = replace(
            base, receive_streams=(replace(stream, **{field: None}),)
        ).capabilities
        assert caps.receive_control_stream is None
        assert caps.receive_routing_stream is not None
    caps = replace(
        base, receive_streams=(replace(stream, stream_location=None),)
    ).capabilities
    assert caps.receive_routing_stream is None
    assert caps.receive_control_stream is not None


def test_capabilities_refresh_with_mode_and_do_not_cache_busy_state():
    base = snapshot()
    busy = replace(base.receive_streams[0], processing=True)
    assert (
        replace(base, receive_streams=(busy,)).capabilities.receive_control_stream
        == busy
    )
    assert (
        replace(base, device_mode="Transmitter").capabilities.receive_control_stream
        is None
    )
    assert base.capabilities.receive_control_stream is not None
    assert base.receive_streams[0].stream_location not in repr(base.capabilities)


@pytest.mark.parametrize(
    "model", ["DM-NVX-D30", "DM-NVX-351", "DM-NVX-352", "DM-NVX-363"]
)
async def test_reboot_preflight_accepts_additional_nvx_models(model):
    base = replace(BEFORE, device=replace(BEFORE.device, model=model))
    client = control_client(
        _response(200, ack(path="Device.DeviceOperations", prop="Reboot")),
        snapshots=[base],
    )
    await client.async_reboot()
    client._session.post.assert_called_once()
