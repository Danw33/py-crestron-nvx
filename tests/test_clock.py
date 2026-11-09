"""Clock discovery and narrow no-replay sync commands."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from crestron_nvx import (
    NvxCapabilities,
    NvxClockInfo,
    NvxConnectionError,
    NvxControlError,
    NvxControlUnsupported,
    NvxResponseError,
)
from crestron_nvx.clock import parse_clock

from .test_client import _response
from .test_control import BEFORE, ack, control_client


def payload(version="2.1.0", enabled=True, servers=None):
    return {
        "Device": {
            "SystemClock": {
                "Version": version,
                "Ntp": {
                    "IsEnabled": enabled,
                    "Servers": servers
                    if servers is not None
                    else {
                        "Server1": {"Address": "time.example.test", "AuthKey": "secret"}
                    },
                },
            }
        }
    }


@pytest.mark.parametrize("version", ["2.1.0", "2.1.1", "2.2.0"])
@pytest.mark.parametrize("enabled", [True, 1, False, 0, None, "true"])
def test_parse(version, enabled):
    info = parse_clock(payload(version, enabled))
    assert info.sync_supported
    assert info.can_sync == (enabled is True or (type(enabled) is int and enabled == 1))
    assert "secret" not in repr(info) and "time.example.test" not in repr(info)
    assert NvxCapabilities.from_snapshot(BEFORE, clock_info=info).ntp_sync


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"Device": None},
        {"Device": {"SystemClock": "unsupported"}},
        payload("2.0.3"),
        payload("bad"),
        payload(None),
        {"Device": {"SystemClock": {"Version": "2.1.0", "Sntp": {}}}},
        {"Device": {"SystemClock": {"Version": "2.1.0", "Ntp": None}}},
    ],
)
def test_unsupported_schema(data):
    assert parse_clock(data) == NvxClockInfo()


@pytest.mark.parametrize(
    "servers",
    [{}, [], {"one": None}, {"one": {"Address": ""}}, {"one": {"Address": 1}}],
)
def test_missing_server(servers):
    assert not parse_clock(payload(servers=servers)).can_sync


async def test_optional_read_and_transport_failure():
    client = control_client()
    client._async_get_read_only_object = AsyncMock(return_value=payload())
    assert (await client.async_get_clock_info()).can_sync
    client._async_get_read_only_object.side_effect = NvxResponseError
    assert await client.async_get_clock_info() == NvxClockInfo()
    client._async_get_read_only_object.side_effect = NvxConnectionError
    with pytest.raises(NvxConnectionError):
        await client.async_get_clock_info()


def sync_client(response=None, info=None, before=BEFORE):
    client = control_client(
        response
        or _response(
            200, ack(path="Device.SystemClock.Ntp", prop="ForceSynchronizationNow")
        ),
        [before],
    )
    client._async_get_clock_info = AsyncMock(
        return_value=info or NvxClockInfo(True, True, True)
    )
    return client


@pytest.mark.parametrize(
    "path",
    [
        "Device.SystemClock.Ntp",
        "Device.SystemClock.Ntp.ForceSynchronizationNow",
    ],
)
async def test_command_is_only_sync_flag_no_readback(path):
    client = sync_client(_response(200, ack(path=path, prop="ForceSynchronizationNow")))
    await client.async_sync_clock(expected_device_id="test")
    assert client._session.post.call_args.kwargs["json"] == {
        "Device": {"SystemClock": {"Ntp": {"ForceSynchronizationNow": True}}}
    }
    client._session.post.assert_called_once()
    client._async_get_snapshot.assert_awaited_once()
    client._async_get_clock_info.assert_awaited_once()


async def test_parent_object_ack():
    client = sync_client(_response(200, ack(path="Device.SystemClock")))
    await client.async_sync_clock()
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "info",
    [
        NvxClockInfo(),
        NvxClockInfo(True, False, True),
        NvxClockInfo(True, None, True),
        NvxClockInfo(True, True, False),
    ],
)
async def test_not_ready_never_posts(info):
    client = sync_client(info=info)
    with pytest.raises(NvxControlUnsupported):
        await client.async_sync_clock()
    client._session.post.assert_not_called()


@pytest.mark.parametrize("identity", ["", " ", 1])
async def test_invalid_identity_no_io(identity):
    client = sync_client()
    with pytest.raises(ValueError):
        await client.async_sync_clock(expected_device_id=identity)
    client._async_get_snapshot.assert_not_awaited()


async def test_wrong_identity_and_non_nvx():
    client = sync_client()
    with pytest.raises(NvxControlError):
        await client.async_sync_clock(expected_device_id="different")
    client._async_get_clock_info.assert_not_awaited()
    client = sync_client(
        before=replace(BEFORE, device=replace(BEFORE.device, model="CP4"))
    )
    with pytest.raises(NvxControlUnsupported):
        await client.async_sync_clock()
    client._session.post.assert_not_called()


@pytest.mark.parametrize("error", [TimeoutError, asyncio.CancelledError])
async def test_no_replay_and_lock_release(error):
    client = sync_client()
    client._session.post.side_effect = error
    with pytest.raises(NvxConnectionError if error is TimeoutError else error):
        await client.async_sync_clock()
    client._session.post.assert_called_once()
    assert not client._io_lock.locked()


@pytest.mark.parametrize(
    "response",
    [
        _response(403, {}),
        _response(200, ack(path="Device.SystemClock.Ntp", status=3)),
        _response(200, ack(path="Device.SystemClock.Ntp.Servers")),
        _response(200, ack(path="Device.SystemClock.Ntp", prop="IsEnabled")),
    ],
)
async def test_rejected_or_unrelated_ack_not_replayed(response):
    client = sync_client(response)
    with pytest.raises(NvxControlError):
        await client.async_sync_clock()
    client._session.post.assert_called_once()
