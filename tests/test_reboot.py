"""An explicit reboot uses one narrow request and never replays it."""

import asyncio
from dataclasses import replace

import pytest

from crestron_nvx import (
    NvxConnectionError,
    NvxControlError,
    NvxControlUnsupported,
    NvxPermissionError,
)

from .test_client import _response
from .test_control import BEFORE, ack, control_client


async def test_one_reboot_post_without_readback():
    client = control_client(
        _response(200, ack(path="Device.DeviceOperations", prop="Reboot")),
        snapshots=[BEFORE],
    )
    assert await client.async_reboot(expected_device_id="test") is None
    call = client._session.post.call_args
    assert str(call.args[0]) == "https://192.0.2.1/Device"
    assert call.kwargs["json"] == {"Device": {"DeviceOperations": {"Reboot": True}}}
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["ssl"] is False
    assert call.kwargs["timeout"].total == 10
    client._async_get_snapshot.assert_awaited_once()
    client._session.post.assert_called_once()


@pytest.mark.parametrize("identity", ["", " ", 1])
async def test_invalid_expected_identity_has_no_io(identity):
    client = control_client()
    with pytest.raises(ValueError):
        await client.async_reboot(expected_device_id=identity)
    client._async_get_snapshot.assert_not_awaited()
    client._session.post.assert_not_called()


async def test_wrong_identity_and_unknown_model_refuse_post():
    client = control_client(snapshots=[BEFORE])
    with pytest.raises(NvxControlError):
        await client.async_reboot(expected_device_id="other")
    client._session.post.assert_not_called()

    unsupported = replace(BEFORE, device=replace(BEFORE.device, model="unknown"))
    client = control_client(snapshots=[unsupported])
    with pytest.raises(NvxControlUnsupported):
        await client.async_reboot()
    client._session.post.assert_not_called()


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (ack(path="Device.DeviceSpecific", prop="Reboot"), NvxControlError),
        (ack(path="Device.DeviceOperations", prop="Reset"), NvxControlError),
        (
            ack(path="Device.DeviceOperations", prop="Reboot", status=3),
            NvxControlUnsupported,
        ),
        (ack(path="Device.DeviceOperations", prop="Reboot", status=1), NvxControlError),
        ({}, NvxControlError),
    ],
)
async def test_unrelated_or_failed_ack_is_not_retried(payload, error):
    client = control_client(_response(200, payload), snapshots=[BEFORE])
    with pytest.raises(error):
        await client.async_reboot()
    client._session.post.assert_called_once()


@pytest.mark.parametrize(
    "status,error", [(403, NvxPermissionError), (500, NvxControlError)]
)
async def test_http_error_is_not_retried(status, error):
    client = control_client(_response(status, {}), snapshots=[BEFORE])
    with pytest.raises(error):
        await client.async_reboot()
    client._session.post.assert_called_once()


async def test_connection_loss_may_be_applied_and_is_not_retried():
    client = control_client(snapshots=[BEFORE])
    client._session.post.side_effect = TimeoutError
    with pytest.raises(NvxConnectionError, match="outcome uncertain"):
        await client.async_reboot()
    client._session.post.assert_called_once()


async def test_cancel_releases_lock_and_does_not_replay():
    client = control_client(snapshots=[BEFORE])
    client._session.post.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await client.async_reboot()
    assert not client._io_lock.locked()
    client._session.post.assert_called_once()
