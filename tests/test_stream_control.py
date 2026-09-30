"""Start/stop act only on the primary slot of the current device direction."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from crestron_nvx import (
    NvxConnectionError,
    NvxControlError,
    NvxControlUnsupported,
    NvxPermissionError,
    NvxStream,
)

from .test_client import _response
from .test_control import BEFORE, ack, control_client


def snapshot(direction="receive", status="Stream stopped", **stream_changes):
    stream = NvxStream(
        "primary",
        direction,
        slot_index=0,
        status=status,
        processing=False,
        stream_location="rtsp://192.0.2.20/live.sdp",
    )
    return replace(
        BEFORE,
        device_mode="Receiver" if direction == "receive" else "Transmitter",
        **{f"{direction}_streams": (replace(stream, **stream_changes),)},
    )


@pytest.mark.parametrize(
    "model,mode,direction,expected",
    [
        ("DM-NVX-350", "Receiver", "receive", True),
        ("DM-NVX-360", "Receiver", "receive", True),
        ("DM-NVX-E30", "Receiver", "receive", False),
        ("DM-NVX-350", "Transmitter", "transmit", True),
        ("DM-NVX-360", "Transmitter", "transmit", True),
        ("DM-NVX-E30", "Transmitter", "transmit", True),
        ("DM-NVX-350", "Receiver", "transmit", False),
        ("DM-NVX-350", "Transmitter", "receive", False),
        ("Unknown", "Receiver", "receive", False),
    ],
)
def test_capabilities(model, mode, direction, expected):
    before = snapshot(direction)
    before = replace(
        before, device=replace(before.device, model=model), device_mode=mode
    )
    assert (before.primary_control_stream(direction) is not None) == expected
    assert before.primary_control_stream("bad") is None


@pytest.mark.parametrize("direction", ["receive", "transmit"])
@pytest.mark.parametrize("running", [True, False])
@pytest.mark.parametrize(
    "path_suffix", ["", ".Streams.0", ".Streams[0]", ".Streams[0].{property}"]
)
async def test_fixed_payload_and_verified_status(direction, running, path_suffix):
    obj = "StreamReceive" if direction == "receive" else "StreamTransmit"
    prop = "Start" if running else "Stop"
    before = snapshot(direction)
    after = snapshot(direction, "STREAM STARTED" if running else " Stream Stopped ")
    client = control_client(
        _response(
            200, ack(path=f"Device.{obj}{path_suffix.format(property=prop)}", prop=prop)
        ),
        [before, after],
    )
    assert (
        await client.async_set_stream_running(
            direction, running, expected_device_id="test"
        )
        == after
    )
    call = client._session.post.call_args
    assert call.kwargs["json"] == {"Device": {obj: {"Streams": [{prop: True}]}}}
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["timeout"].total == 10
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "direction,running",
    [
        ("bad", True),
        (None, True),
        ({}, False),
        ("receive", 1),
        ("transmit", None),
        ("receive", "false"),
    ],
)
async def test_invalid_arguments_no_io(direction, running):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_stream_running(direction, running)
    client._async_get_snapshot.assert_not_awaited()


@pytest.mark.parametrize("identity", ["", " ", 1])
async def test_invalid_identity_no_io(identity):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_stream_running(
            "receive", True, expected_device_id=identity
        )
    client._async_get_snapshot.assert_not_awaited()


@pytest.mark.parametrize(
    "before",
    [
        replace(snapshot(), device_mode="Transmitter"),
        snapshot(processing=True),
        snapshot(processing=None),
        snapshot(slot_index=None),
        snapshot(status=None),
        replace(snapshot(), receive_streams=()),
        snapshot(stream_location=""),
        snapshot(stream_location="https://example.com/live"),
    ],
)
async def test_unsafe_start_refused(before):
    client = control_client(snapshots=[before])
    with pytest.raises(NvxControlUnsupported):
        await client.async_set_stream_running("receive", True)
    client._session.post.assert_not_called()


async def test_wrong_identity_and_stopping_without_url():
    client = control_client(snapshots=[snapshot()])
    with pytest.raises(NvxControlError):
        await client.async_set_stream_running(
            "receive", False, expected_device_id="wrong"
        )
    client._session.post.assert_not_called()
    stopped = snapshot(stream_location="")
    client = control_client(
        _response(200, ack(path="Device.StreamReceive")), [stopped, stopped]
    )
    assert await client.async_set_stream_running("receive", False) == stopped


@pytest.mark.parametrize(
    "after",
    [
        snapshot(),
        snapshot("receive", "Stream started", processing=True),
        replace(snapshot("receive", "Stream started"), device_mode="Transmitter"),
    ],
)
async def test_incomplete_readback_is_not_success_or_replayed(after):
    client = control_client(
        _response(200, ack(path="Device.StreamReceive")), [snapshot(), *([after] * 5)]
    )
    with (
        patch("crestron_nvx.client.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(NvxControlError, match="uncertain"),
    ):
        await client.async_set_stream_running("receive", True)
    client._session.post.assert_called_once()


async def test_delayed_readback_and_changed_identity():
    before, after = snapshot(), snapshot("receive", "Stream started")
    client = control_client(
        _response(200, ack(path="Device.StreamReceive")), [before, before, after]
    )
    with patch("crestron_nvx.client.asyncio.sleep", new_callable=AsyncMock):
        assert await client.async_set_stream_running("receive", True) == after
    client = control_client(
        _response(200, ack(path="Device.StreamReceive")),
        [before, replace(after, device=replace(after.device, device_id="wrong"))],
    )
    with pytest.raises(NvxControlError, match="identity changed"):
        await client.async_set_stream_running("receive", True)
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "payload",
    [
        ack(path="Device.StreamTransmit"),
        ack(path="Device.StreamReceive", prop="Stop"),
        ack(path="Device.StreamReceive.Streams[1].Start"),
        ack(path="Device.StreamReceive.Streams[0].Stop"),
        ack(path="Device.StreamReceive", status=1),
        ack(path="Device.StreamReceive", status=3),
        {},
    ],
)
async def test_wrong_or_failed_ack_never_replayed(payload):
    client = control_client(_response(200, payload), [snapshot()])
    with pytest.raises(NvxControlError):
        await client.async_set_stream_running("receive", True)
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "status,error", [(403, NvxPermissionError), (302, NvxControlError)]
)
async def test_http_failures(status, error):
    client = control_client(_response(status, {}), [snapshot()])
    with pytest.raises(error):
        await client.async_set_stream_running("receive", False)
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "failure,error",
    [
        (TimeoutError, NvxConnectionError),
        (asyncio.CancelledError, asyncio.CancelledError),
    ],
)
async def test_interruption_releases_lock_without_retry(failure, error):
    client = control_client(snapshots=[snapshot()])
    client._session.post.side_effect = failure
    with pytest.raises(error):
        await client.async_set_stream_running("receive", False)
    assert not client._io_lock.locked()
    client._session.post.assert_called_once()
