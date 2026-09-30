"""Primary stream routing is narrow, explicit, identity-checked and verified."""

import asyncio
from dataclasses import replace

import pytest

from crestron_nvx import (
    NvxControlError,
    NvxControlUnsupported,
    NvxStream,
    is_valid_stream_location,
)
from crestron_nvx.client import _parse_streams

from .test_client import _response
from .test_control import BEFORE, ack, control_client

LOCATION = "rtsp://192.0.2.20:554/live.sdp"
STREAM = NvxStream(
    "receive_0",
    "receive",
    slot_index=0,
    stream_location="",
    processing=False,
    session_initiation="Multicast via RTSP",
)
BASE = replace(BEFORE, device_mode="Receiver", receive_streams=(STREAM,))
AFTER = replace(BASE, receive_streams=(replace(STREAM, stream_location=LOCATION),))


@pytest.mark.parametrize("value", [LOCATION, "rtsp://nvx.example.local/live.sdp"])
def test_valid_locations(value):
    assert is_valid_stream_location(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "",
        "x" * 2049,
        "https://192.0.2.1/a",
        "rtsp:///a",
        "rtsp://user:secret@192.0.2.1/a",
        "rtsp://192.0.2.1/a?q=secret",
        "rtsp://192.0.2.1/a#f",
        "rtsp://192.0.2.1/",
        "rtsp://192.0.2.1:0/a",
        "rtsp://192.0.2.1:99999/a",
        "rtsp://[::1]/a",
        "rtsp://127.0.0.1/a",
        "rtsp://0.0.0.0/a",
        "rtsp://239.0.0.1/a",
        "rtsp://169.254.1.1/a",
        "rtsp://localhost/a",
        "rtsp://-bad/a",
        "rtsp://bad_.local/a",
        "rtsp://192.0.2.1/a\n",
        "rtsp://192.0.2.1/a\\b",
        "rtsp://[bad/a",
    ],
)
async def test_invalid_location_has_no_io(value):
    assert not is_valid_stream_location(value)
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_receive_stream_location(value)
    client._async_get_snapshot.assert_not_awaited()


@pytest.mark.parametrize("identity", ["", " ", 2])
async def test_invalid_identity(identity):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_receive_stream_location(
            LOCATION, expected_device_id=identity
        )
    client._async_get_snapshot.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    [
        "Device.StreamReceive",
        "Device.StreamReceive.Streams.0",
        "Device.StreamReceive.Streams.0.StreamLocation",
        "Device.StreamReceive.Streams[0]",
        "Device.StreamReceive.Streams[0].StreamLocation",
    ],
)
async def test_exact_primary_partial_payload_and_readback(path):
    client = control_client(
        _response(200, ack(path=path, prop="StreamLocation")), [BASE, AFTER]
    )
    assert (
        await client.async_set_receive_stream_location(
            LOCATION, expected_device_id="test"
        )
        == AFTER
    )
    call = client._session.post.call_args
    assert call.kwargs["json"] == {
        "Device": {"StreamReceive": {"Streams": [{"StreamLocation": LOCATION}]}}
    }
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["timeout"].total == 10
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "snapshot",
    [
        replace(BASE, device_mode="Transmitter"),
        replace(BASE, device=replace(BASE.device, model="DM-NVX-E30")),
        replace(BASE, receive_streams=()),
        *[
            replace(BASE, receive_streams=(replace(STREAM, **change),))
            for change in (
                {"slot_index": None},
                {"stream_location": None},
                {"processing": True},
                {"processing": None},
                {"session_initiation": "ByReceiver"},
            )
        ],
    ],
)
async def test_unsupported_or_busy(snapshot):
    client = control_client(snapshots=[snapshot])
    with pytest.raises(NvxControlUnsupported):
        await client.async_set_receive_stream_location(LOCATION)
    client._session.post.assert_not_called()


async def test_identity_mismatch_and_noop():
    client = control_client(snapshots=[BASE])
    with pytest.raises(NvxControlError):
        await client.async_set_receive_stream_location(
            LOCATION, expected_device_id="wrong"
        )
    client._session.post.assert_not_called()
    client = control_client(snapshots=[AFTER])
    assert await client.async_set_receive_stream_location(LOCATION) == AFTER
    client._session.post.assert_not_called()


@pytest.mark.parametrize(
    "after", [BASE, replace(AFTER, device=replace(AFTER.device, device_id="wrong"))]
)
async def test_readback_failure_never_replays(after):
    client = control_client(
        _response(200, ack(path="Device.StreamReceive")), [BASE, after, after, after]
    )
    with pytest.raises(NvxControlError):
        await client.async_set_receive_stream_location(LOCATION)
    client._session.post.assert_called_once()


async def test_delayed_readback_and_cancel():
    client = control_client(
        _response(200, ack(path="Device.StreamReceive")), [BASE, BASE, AFTER]
    )
    assert await client.async_set_receive_stream_location(LOCATION) == AFTER
    client = control_client(snapshots=[BASE])
    client._session.post.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await client.async_set_receive_stream_location(LOCATION)
    assert not client._io_lock.locked()


@pytest.mark.parametrize(
    "path",
    [
        "Device.StreamReceive.Streams.1",
        [],
        {},
        "Device.StreamTransmit",
        "Device.DeviceSpecific",
    ],
)
async def test_unrelated_ack_rejected(path):
    client = control_client(_response(200, ack(path=path)), [BASE])
    with pytest.raises(NvxControlError):
        await client.async_set_receive_stream_location(LOCATION)
    client._session.post.assert_called_once()


def test_parser_preserves_slots_without_guessing_malformed_collections():
    raw = {
        "StreamLocation": LOCATION,
        "Processing": 0,
        "SessionInitiation": "Multicast via RTSP",
    }
    for collection, index in [
        ([raw, raw], 0),
        ([None, raw], None),
        ({"Stream1": raw}, None),
    ]:
        streams = _parse_streams(
            {"Device": {"StreamReceive": {"Streams": collection}}}, "receive"
        )
        assert streams[0].slot_index == index
        assert streams[0].stream_location == LOCATION
        assert streams[0].processing is False
        assert LOCATION not in repr(streams[0])
    empty = _parse_streams(
        {
            "Device": {
                "StreamReceive": {
                    "Streams": [{"StreamLocation": ""}, {"StreamLocation": 1}]
                }
            }
        },
        "receive",
    )
    assert empty[0].stream_location == ""
    assert empty[1].stream_location is None
