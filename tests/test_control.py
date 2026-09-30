"""Exercise fixed LED payloads and conservative command failure handling."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError

from crestron_nvx import (
    NvxConnectionError,
    NvxControlError,
    NvxControlUnsupported,
    NvxDeviceInfo,
    NvxPermissionError,
    NvxResponseError,
    NvxSnapshot,
)
from crestron_nvx.client import _validate_led_result

from .test_client import _client, _response

BEFORE = NvxSnapshot(
    device=NvxDeviceInfo(device_id="test", name="Test", model="DM-NVX-350"),
    leds_enabled=False,
)
AFTER = replace(BEFORE, leds_enabled=True)


def ack(status=0, path="Device.DeviceSpecific", prop=None):
    result = {"Path": path, "StatusId": status}
    if prop is not None:
        result["Property"] = prop
    return {"Actions": [{"Operation": "SetPartial", "Results": [result]}]}


def control_client(response=None, snapshots=None):
    client = _client([], [response or _response(200, ack())])
    client._async_get_snapshot = AsyncMock(side_effect=snapshots or [BEFORE, AFTER])
    return client


async def test_fixed_payload_and_readback():
    client = control_client(_response(200, ack(), cookies={"token": "new"}))
    client._cookies = {"token": "old"}
    assert await client.async_set_leds_enabled(True) == AFTER
    call = client._session.post.call_args
    assert str(call.args[0]) == "https://192.0.2.1/Device"
    assert call.kwargs["json"] == {"Device": {"DeviceSpecific": {"LedsEnabled": True}}}
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["ssl"] is False
    assert client._cookies["token"] == "new"
    assert client._async_get_snapshot.await_count == 2
    client._session.post.assert_called_once()


@pytest.mark.parametrize("value", [1, 0, "true", None, {}])
async def test_invalid_input_never_sends(value):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_leds_enabled(value)
    client._async_get_snapshot.assert_not_awaited()
    client._session.post.assert_not_called()


async def test_noop_and_unsupported():
    client = control_client(snapshots=[AFTER])
    assert await client.async_set_leds_enabled(True) == AFTER
    client._session.post.assert_not_called()
    client = control_client(snapshots=[replace(BEFORE, leds_enabled=None)])
    with pytest.raises(NvxControlUnsupported):
        await client.async_set_leds_enabled(True)
    client._session.post.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"Actions": []},
        {"Actions": [None]},
        {"Actions": [{"Operation": "Other"}]},
        {"Actions": [{"Operation": "SetPartial", "Results": []}]},
        {"Actions": [{"Operation": "SetPartial", "Results": [None]}]},
        ack(path="Device.Other"),
        ack(prop="VideoSource"),
        ack(prop={}),
        ack(status=True),
        ack(status="0"),
        ack(status=-1),
        ack(status=1),
        ack(status=2),
        ack(status=-4),
        {
            "Actions": [
                {
                    "Operation": "SetPartial",
                    "Results": [
                        {"Path": "Device.DeviceSpecific", "StatusId": 0},
                        {"StatusId": -4},
                    ],
                }
            ]
        },
    ],
)
def test_reject_invalid_or_unsuccessful_ack(payload):
    with pytest.raises(NvxControlError):
        _validate_led_result(payload)


@pytest.mark.parametrize(
    "payload",
    [ack(), ack(prop="LedsEnabled"), ack(path="Device.DeviceSpecific.LedsEnabled")],
)
def test_accept_relevant_success(payload):
    _validate_led_result(payload)


@pytest.mark.parametrize("status", [-2, 3])
def test_unsupported_result(status):
    with pytest.raises(NvxControlUnsupported):
        _validate_led_result(ack(status))


@pytest.mark.parametrize(
    "status,error",
    [
        (401, NvxPermissionError),
        (403, NvxPermissionError),
        (302, NvxControlError),
        (500, NvxControlError),
    ],
)
async def test_http_failure_never_replayed(status, error):
    client = control_client(_response(status))
    with pytest.raises(error):
        await client.async_set_leds_enabled(True)
    client._session.post.assert_called_once()
    client._async_get_snapshot.assert_awaited_once()


@pytest.mark.parametrize("error", [TimeoutError(), ClientError()])
async def test_transport_failure_never_replayed(error):
    client = control_client()
    client._session.post.side_effect = error
    with pytest.raises(NvxConnectionError):
        await client.async_set_leds_enabled(True)
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "body,error",
    [(b"not json", NvxControlError), (b"x" * (2 * 1024 * 1024 + 1), NvxResponseError)],
)
async def test_bounded_response(body, error):
    client = control_client(_response(200, raw_body=body))
    with pytest.raises(error):
        await client.async_set_leds_enabled(True)
    client._session.post.assert_called_once()


async def test_readback_retry_does_not_repeat_write():
    client = control_client(snapshots=[BEFORE, BEFORE, AFTER])
    assert await client.async_set_leds_enabled(True) == AFTER
    client._session.post.assert_called_once()


async def test_mismatch_or_changed_identity():
    client = control_client(snapshots=[BEFORE] * 4)
    with pytest.raises(NvxControlError):
        await client.async_set_leds_enabled(True)
    client._session.post.assert_called_once()
    client = control_client(
        snapshots=[
            BEFORE,
            replace(AFTER, device=replace(AFTER.device, device_id="other")),
        ]
    )
    with pytest.raises(NvxControlError):
        await client.async_set_leds_enabled(True)


async def test_cancellation_releases_lock_without_replay():
    client = control_client()
    client._session.post.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await client.async_set_leds_enabled(True)
    assert not client._io_lock.locked()
    client._session.post.assert_called_once()


async def test_concurrent_read_waits_for_command():
    client = control_client()
    started, finish = asyncio.Event(), asyncio.Event()

    async def post(enabled):
        started.set()
        await finish.wait()

    client._async_post_leds = post
    client._async_get_snapshot.side_effect = [BEFORE, AFTER, AFTER]
    task = asyncio.create_task(client.async_set_leds_enabled(True))
    await started.wait()
    read = asyncio.create_task(client.async_get_snapshot())
    await asyncio.sleep(0)
    assert client._async_get_snapshot.await_count == 1
    finish.set()
    await asyncio.gather(task, read)
    assert client._async_get_snapshot.await_count == 3


@pytest.mark.parametrize("identity", ["", " ", 4])
async def test_invalid_expected_identity(identity):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_set_leds_enabled(True, expected_device_id=identity)
    client._session.post.assert_not_called()


async def test_wrong_endpoint_never_written():
    client = control_client()
    with pytest.raises(NvxControlError):
        await client.async_set_leds_enabled(True, expected_device_id="different")
    client._session.post.assert_not_called()


async def test_off_payload_and_identity_check():
    client = control_client(snapshots=[AFTER, BEFORE])
    client._verify_ssl = True
    assert (
        await client.async_set_leds_enabled(False, expected_device_id="test") == BEFORE
    )
    assert client._session.post.call_args.kwargs["json"] == {
        "Device": {"DeviceSpecific": {"LedsEnabled": False}}
    }
    assert client._session.post.call_args.kwargs["ssl"] is True


async def test_real_preflight_renews_expired_session_before_single_write():
    info = {"Device": {"DeviceInfo": {"DeviceId": "test", "Model": "DM-NVX-350"}}}

    def snapshot_responses(state):
        return [
            _response(200, info),
            _response(200, {"Device": {"DeviceSpecific": {"LedsEnabled": state}}}),
            *[_response(404) for _ in range(3)],
        ]

    client = _client(
        [
            _response(401),
            _response(200),
            *snapshot_responses(False),
            *snapshot_responses(True),
        ],
        [_response(200, cookies={"session": "fresh"}), _response(200, ack())],
    )
    client._cookies = {"session": "expired"}
    result = await client.async_set_leds_enabled(True)
    assert result.leds_enabled is True
    posts = client._session.post.call_args_list
    assert len(posts) == 2
    assert str(posts[0].args[0]).endswith("/userlogin.html")
    assert str(posts[1].args[0]).endswith("/Device")


async def test_readback_failure_never_replays():
    client = control_client(snapshots=[BEFORE, NvxConnectionError()])
    with pytest.raises(NvxConnectionError):
        await client.async_set_leds_enabled(True)
    client._session.post.assert_called_once()
