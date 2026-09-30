"""Primary audio source capabilities and verified explicit writes."""

from dataclasses import replace

import pytest

from crestron_nvx import (
    NvxAvPort,
    NvxControlError,
    NvxControlUnsupported,
    NvxPermissionError,
    NvxStream,
)

from .test_client import _response
from .test_control import BEFORE, ack, control_client

BASE = replace(
    BEFORE,
    device_mode="Transmitter",
    audio_source="AudioFollowsVideo",
    audio_mode="Insert",
    auto_input_routing_enabled=False,
    av_ports=(
        NvxAvPort("input_slot0_hdmi_0", "INPUT 1", "input"),
        NvxAvPort("input_slot1_hdmi_0", "INPUT 2", "input"),
    ),
    receive_streams=(NvxStream("receive_0", "receive"),),
)


@pytest.mark.parametrize(
    ("model", "mode", "analog_mode", "expected"),
    [
        (
            "DM-NVX-350",
            "Transmitter",
            "Insert",
            ("AudioFollowsVideo", "Input1", "Input2", "AnalogAudio"),
        ),
        (
            "DM-NVX-350",
            "Receiver",
            "Extract",
            ("AudioFollowsVideo", "Input1", "Input2", "PrimaryStreamAudio"),
        ),
        (
            "DM-NVX-360",
            "Receiver",
            "Insert",
            ("AudioFollowsVideo", "Input1", "AnalogAudio", "PrimaryStreamAudio"),
        ),
        ("DM-NVX-E30", "Transmitter", None, ("AudioFollowsVideo", "Input1")),
        ("DM-NVX-E30", "Receiver", None, ()),
        ("Other", "Transmitter", "Insert", ()),
    ],
)
def test_documented_options_follow_model_mode_and_connector(
    model, mode, analog_mode, expected
):
    snapshot = replace(
        BASE,
        device=replace(BASE.device, model=model),
        device_mode=mode,
        audio_mode=analog_mode,
    )
    assert snapshot.audio_source_options == expected


def test_unknown_or_unsupported_configured_state_is_not_overwritten():
    assert replace(BASE, audio_source=None).audio_source_options == ()
    assert replace(BASE, audio_source="NoAudioSelected").audio_source_options == ()
    assert replace(BASE, audio_source="SecondaryStreamAudio").audio_source_options == ()
    assert (
        replace(
            BASE, audio_mode="Extract", audio_source="AnalogAudio"
        ).audio_source_options
        == ()
    )
    assert (
        replace(
            BASE,
            device_mode="Receiver",
            receive_streams=(),
            audio_source="PrimaryStreamAudio",
        ).audio_source_options
        == ()
    )
    assert replace(BASE, av_ports=()).audio_source_options == (
        "AudioFollowsVideo",
        "AnalogAudio",
    )


async def test_fixed_audio_payload_and_configured_readback():
    after = replace(BASE, audio_source="Input2", active_audio_source="Input1")
    client = control_client(_response(200, ack(prop="AudioSource")), [BASE, after])
    assert (
        await client.async_set_audio_source("Input2", expected_device_id="test")
        == after
    )
    call = client._session.post.call_args
    assert str(call.args[0]) == "https://192.0.2.1/Device"
    assert call.kwargs["json"] == {
        "Device": {"DeviceSpecific": {"AudioSource": "Input2"}}
    }
    assert call.kwargs["allow_redirects"] is False
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "value", [None, True, 1, {}, "input1", "SecondaryStreamAudio", ""]
)
async def test_invalid_value_fails_before_network_io(value):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_audio_source(value)
    client._async_get_snapshot.assert_not_awaited()


@pytest.mark.parametrize(
    "snapshot,source,identity",
    [
        (BASE, "PrimaryStreamAudio", None),
        (replace(BASE, auto_input_routing_enabled=True), "Input1", None),
        (replace(BASE, auto_input_routing_enabled=None), "Input1", None),
        (BASE, "Input1", "different"),
    ],
)
async def test_preflight_blocks_unsupported_routing_or_wrong_identity(
    snapshot, source, identity
):
    client = control_client(snapshots=[snapshot])
    with pytest.raises(NvxControlError):
        await client.async_set_audio_source(source, expected_device_id=identity)
    client._session.post.assert_not_called()


async def test_existing_source_is_noop_even_with_auto_routing():
    before = replace(BASE, auto_input_routing_enabled=True)
    client = control_client(snapshots=[before])
    assert await client.async_set_audio_source("AudioFollowsVideo") == before
    client._session.post.assert_not_called()


async def test_delayed_readback_does_not_replay_post():
    after = replace(BASE, audio_source="Input1")
    client = control_client(snapshots=[BASE, BASE, after])
    assert await client.async_set_audio_source("Input1") == after
    client._session.post.assert_called_once()


async def test_readback_mismatch_and_identity_change_are_uncertain():
    client = control_client(snapshots=[BASE] * 4)
    with pytest.raises(NvxControlError):
        await client.async_set_audio_source("Input1")
    client._session.post.assert_called_once()
    client = control_client(
        snapshots=[BASE, replace(BASE, device=replace(BASE.device, device_id="other"))]
    )
    with pytest.raises(NvxControlError):
        await client.async_set_audio_source("Input1")
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "response,error",
    [
        (_response(403, {}), NvxPermissionError),
        (_response(200, ack(prop="VideoSource")), NvxControlError),
        (_response(200, ack(status=3, prop="AudioSource")), NvxControlUnsupported),
    ],
)
async def test_denied_or_irrelevant_ack_never_retries(response, error):
    client = control_client(response, [BASE])
    with pytest.raises(error):
        await client.async_set_audio_source("Input1")
    client._session.post.assert_called_once()
