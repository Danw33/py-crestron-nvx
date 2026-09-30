"""Conservative source capabilities and explicit verified writes."""

import asyncio
from dataclasses import replace

import pytest

from crestron_nvx import (
    NvxAvPort,
    NvxControlError,
    NvxControlUnsupported,
    NvxPermissionError,
)

from .test_client import _response
from .test_control import BEFORE, ack, control_client

BASE = replace(
    BEFORE,
    device_mode="Transmitter",
    video_source="None",
    auto_input_routing_enabled=False,
    av_ports=tuple(
        NvxAvPort(f"input_slot{i}_hdmi_0", f"Input {i + 1}", "input") for i in range(2)
    ),
)


@pytest.mark.parametrize(
    "model,mode,expected",
    [
        ("DM-NVX-350", "Transmitter", ("None", "Input1", "Input2")),
        ("DM-NVX-350", "Receiver", ("None", "Input1", "Input2", "Stream")),
        ("DM-NVX-360", "Receiver", ("None", "Input1", "Input2", "Stream")),
        ("DM-NVX-E30", "Transmitter", ("None", "Input1", "Input2")),
        ("Other", "Receiver", ()),
        ("DM-NVX-350", "Unknown", ()),
    ],
)
def test_options(model, mode, expected):
    # Deliberately identical topology: the model must not override observations.
    snapshot = replace(BASE, device=replace(BASE.device, model=model), device_mode=mode)
    assert snapshot.video_source_options == expected


def test_missing_fields_and_topology():
    assert replace(BASE, video_source=None).video_source_options == ()
    assert replace(BASE, video_source="Future").video_source_options == ()
    assert replace(BASE, av_ports=()).video_source_options == ("None",)
    assert replace(
        BASE, av_ports=(NvxAvPort("input_index0_hdmi_0", "Input 1", "input"),)
    ).video_source_options == ("None",)


async def test_write_only_source_and_verify_configured_not_active():
    after = replace(BASE, video_source="Input2", active_video_source="None")
    client = control_client(_response(200, ack(prop="VideoSource")), [BASE, after])
    assert (
        await client.async_set_video_source("Input2", expected_device_id="test")
        == after
    )
    assert client._session.post.call_args.kwargs["json"] == {
        "Device": {"DeviceSpecific": {"VideoSource": "Input2"}}
    }
    assert client._session.post.call_args.kwargs["allow_redirects"] is False
    client._session.post.assert_called_once()


@pytest.mark.parametrize("source", [None, True, {}, "input1", "Input3", ""])
async def test_invalid_source_no_io(source):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_video_source(source)
    client._async_get_snapshot.assert_not_awaited()


@pytest.mark.parametrize("identity", ["", " ", 3])
async def test_invalid_identity_no_io(identity):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_video_source("Input1", expected_device_id=identity)
    client._async_get_snapshot.assert_not_awaited()


@pytest.mark.parametrize(
    "snapshot,source,identity",
    [
        (BASE, "Stream", None),
        (replace(BASE, auto_input_routing_enabled=True), "Input1", None),
        (replace(BASE, auto_input_routing_enabled=None), "Input1", None),
        (BASE, "Input1", "different"),
    ],
)
async def test_preflight_refuses_unsafe_change(snapshot, source, identity):
    client = control_client(snapshots=[snapshot])
    with pytest.raises(NvxControlError):
        await client.async_set_video_source(source, expected_device_id=identity)
    client._session.post.assert_not_called()


async def test_noop_even_when_auto_routing_enabled():
    before = replace(BASE, auto_input_routing_enabled=True)
    client = control_client(snapshots=[before])
    assert await client.async_set_video_source("None") == before
    client._session.post.assert_not_called()


async def test_delayed_readback_and_uncertain_failure():
    after = replace(BASE, video_source="Input1")
    client = control_client(snapshots=[BASE, BASE, after])
    assert await client.async_set_video_source("Input1") == after
    client._session.post.assert_called_once()
    client = control_client(snapshots=[BASE] * 4)
    with pytest.raises(NvxControlError):
        await client.async_set_video_source("Input1")
    client._session.post.assert_called_once()


async def test_changed_identity_after_post():
    client = control_client(
        snapshots=[BASE, replace(BASE, device=replace(BASE.device, device_id="other"))]
    )
    with pytest.raises(NvxControlError):
        await client.async_set_video_source("Input1")
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "response,error",
    [
        (_response(403, {}), NvxPermissionError),
        (_response(200, ack(prop="LedsEnabled")), NvxControlError),
        (_response(200, ack(status=3, prop="VideoSource")), NvxControlUnsupported),
    ],
)
async def test_denial_or_wrong_ack_no_retry(response, error):
    client = control_client(response, [BASE])
    with pytest.raises(error):
        await client.async_set_video_source("Input1")
    client._session.post.assert_called_once()


async def test_cancel_releases_lock_without_replay():
    client = control_client(snapshots=[BASE, asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await client.async_set_video_source("Input1")
    assert not client._io_lock.locked()
    client._session.post.assert_called_once()
