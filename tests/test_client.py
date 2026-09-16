"""Tests for the read-only API boundary."""

import json
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientError

from crestron_nvx import (
    NvxAuthenticationError,
    NvxClient,
    NvxConnectionError,
    NvxReadPath,
    NvxResponseError,
)

from .conftest import DEVICE_ID


def _response(
    status: int,
    payload: object | None = None,
    *,
    cookies: dict[str, str] | None = None,
    json_error: Exception | None = None,
    raw_body: bytes | None = None,
) -> MagicMock:
    """Return an async-context-manager response."""
    response = MagicMock(status=status)
    response.cookies = SimpleCookie(cookies or {})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    encoded = raw_body if raw_body is not None else json.dumps(payload).encode()
    response.content.read = AsyncMock(
        side_effect=json_error if json_error else [encoded, b""]
    )
    return response


def _client(get: list[object], post: list[object] | None = None) -> NvxClient:
    """Return a client with queued synthetic responses."""
    session = MagicMock()
    session.get = MagicMock(side_effect=get)
    session.post = MagicMock(side_effect=post or [])
    return NvxClient(session, "192.0.2.1", "user", "password", verify_ssl=False)


def test_parse_complete_snapshot() -> None:
    """Parse documented identity and device-specific fields."""
    snapshot = NvxClient._parse_snapshot(
        {
            "Device": {
                "DeviceInfo": {
                    "DeviceId": f" {DEVICE_ID} ",
                    "Name": " Test NVX ",
                    "Model": "DM-NVX-360",
                    "SerialNumber": "serial",
                    "DeviceVersion": "7.1.0",
                    "MacAddress": "00:11:22:33:44:55",
                    "Manufacturer": "Crestron",
                    "RebootReason": "manual",
                }
            }
        },
        {
            "Device": {
                "DeviceSpecific": {
                    "DeviceMode": "Transmitter",
                    "DeviceReady": 1,
                    "ActiveAudioSource": "PrimaryStreamAudio",
                    "ActiveVideoSource": "Stream",
                    "AudioMode": "DAC",
                    "AudioSource": "AudioFollowsVideo",
                    "VideoSource": "Stream",
                    "NaxActiveAudioSource": "PrimaryAudio",
                    "NaxAudioSource": "PrimaryAudio",
                    "AutoInitiationMode": False,
                    "AutoInputRoutingEnabled": True,
                    "IsFrontPanelLockoutEnabled": False,
                    "LedsEnabled": True,
                    "ShowSetupInformationOnOsd": False,
                    "FutureField": 1,
                }
            }
        },
        {
            "Device": {
                "AudioVideoInputOutput": {
                    "Inputs": [
                        {
                            "Name": "Input 1",
                            "Ports": [
                                {
                                    "Uuid": "input-id",
                                    "IsSyncDetected": True,
                                    "HorizontalResolution": 1920,
                                    "VerticalResolution": 1080,
                                    "FramesPerSecond": 60,
                                    "Hdmi": {
                                        "Name": "HDMI 1",
                                        "HdcpState": "HDCP2",
                                    },
                                }
                            ],
                        }
                    ],
                    "Outputs": {
                        "Output1": {
                            "Name": "Output 1",
                            "Ports": [
                                {
                                    "IsSinkConnected": True,
                                    "Hdmi": {"Transmitting": True},
                                }
                            ],
                        }
                    },
                }
            }
        },
        {
            "Device": {
                "StreamReceive": {
                    "Streams": [{"Status": "Started", "CodecReady": True}]
                }
            }
        },
        {
            "Device": {
                "StreamTransmit": {
                    "Streams": [
                        {
                            "UUID": "tx-id",
                            "Status": "Started",
                            "CodecReady": True,
                            "ActiveBitrate": 750,
                            "HorizontalResolution": 1920,
                            "VerticalResolution": 1080,
                            "FramesPerSecond": 60,
                        }
                    ]
                }
            }
        },
    )
    assert snapshot.device.device_id == DEVICE_ID
    assert snapshot.device.name == "Test NVX"
    assert snapshot.device.model == "DM-NVX-360"
    assert snapshot.device_ready is True
    assert snapshot.device_mode == "Transmitter"
    assert snapshot.active_video_source == "Stream"
    assert snapshot.active_audio_source == "PrimaryStreamAudio"
    assert snapshot.audio_mode == "DAC"
    assert snapshot.audio_source == "AudioFollowsVideo"
    assert snapshot.video_source == "Stream"
    assert snapshot.nax_active_audio_source == "PrimaryAudio"
    assert snapshot.nax_audio_source == "PrimaryAudio"
    assert snapshot.auto_initiation_mode is False
    assert snapshot.auto_input_routing_enabled is True
    assert snapshot.front_panel_lockout_enabled is False
    assert snapshot.leds_enabled is True
    assert snapshot.show_setup_information_on_osd is False
    assert snapshot.av_ports[0].port_id == "input-id"
    assert snapshot.av_ports[0].name == "HDMI 1"
    assert snapshot.av_ports[0].resolution == "1920x1080@60"
    assert snapshot.av_ports[1].port_id == "output_0_0"
    assert snapshot.av_ports[1].sink_connected is True
    assert snapshot.av_ports[1].transmitting is True
    assert snapshot.receive_streams[0].stream_id == "receive_0"
    assert snapshot.transmit_streams[0].stream_id == "tx-id"
    assert snapshot.transmit_streams[0].bitrate_mbps == 750
    assert snapshot.transmit_streams[0].resolution == "1920x1080@60"
    assert snapshot.raw_device_specific["FutureField"] == 1


def test_parse_uses_safe_fallbacks() -> None:
    """Use the MAC and model when optional identity fields are absent."""
    snapshot = NvxClient._parse_snapshot(
        {
            "Device": {
                "DeviceInfo": {
                    "DeviceId": "",
                    "MacAddress": "00:11:22:33:44:55",
                    "Model": "DM-NVX-E30",
                }
            }
        },
        {"Device": {"DeviceSpecific": {"DeviceReady": "not-a-bool"}}},
    )
    assert snapshot.device.device_id == "00:11:22:33:44:55"
    assert snapshot.device.name == "DM-NVX-E30"
    assert snapshot.device.manufacturer == "Crestron"
    assert snapshot.device_ready is None


def test_parse_native_boolean() -> None:
    """Continue to accept schema-compliant native booleans."""
    snapshot = NvxClient._parse_snapshot(
        {"Device": {"DeviceInfo": {"DeviceId": "id", "Model": "model"}}},
        {"Device": {"DeviceSpecific": {"DeviceReady": False}}},
    )
    assert snapshot.device_ready is False


def test_inactive_resolution_is_unknown() -> None:
    """Avoid presenting a synthetic 0x0 resolution for inactive signals."""
    snapshot = NvxClient._parse_snapshot(
        {"Device": {"DeviceInfo": {"DeviceId": "id", "Model": "model"}}},
        {},
        {
            "Device": {
                "AudioVideoInputOutput": {
                    "Inputs": [{"Ports": [{"HorizontalResolution": 0}]}]
                }
            }
        },
        {"Device": {"StreamReceive": {"Streams": [{}]}}},
    )
    assert snapshot.av_ports[0].resolution is None
    assert snapshot.receive_streams[0].resolution is None


def test_parse_360_shape_with_optional_fields_omitted() -> None:
    """Parse the sanitized firmware 7.1 DM-NVX-360 shape."""
    snapshot = NvxClient._parse_snapshot(
        {
            "Device": {
                "DeviceInfo": {
                    "DeviceId": "synthetic-360",
                    "Model": "DM-NVX-360",
                    "DeviceVersion": "7.1.5259.00068",
                }
            }
        },
        {"Device": {"DeviceSpecific": {"DeviceReady": 1}}},
        {
            "Device": {
                "AudioVideoInputOutput": {
                    "Inputs": [{"Ports": [{"IsSyncDetected": False}]}],
                    "Outputs": [{"Ports": [{"IsSinkConnected": False}]}],
                }
            }
        },
        {
            "Device": {
                "StreamReceive": {"Streams": [{"Status": "Stopped", "Bitrate": 0}]}
            }
        },
        {
            "Device": {
                "StreamTransmit": {
                    "Streams": [
                        {
                            "UUID": "synthetic-stream",
                            "Status": "Stopped",
                            "Bitrate": 650,
                        }
                    ]
                }
            }
        },
    )
    assert snapshot.device.model == "DM-NVX-360"
    assert snapshot.device_ready is True
    assert snapshot.av_ports[0].sync_detected is False
    assert snapshot.av_ports[1].sink_connected is False
    assert snapshot.receive_streams[0].bitrate_mbps == 0
    assert snapshot.transmit_streams[0].bitrate_mbps == 650


def test_parse_e30_firmware_6_shape() -> None:
    """Parse the sanitized firmware 6.0 DM-NVX-E30 shape."""
    snapshot = NvxClient._parse_snapshot(
        {
            "Device": {
                "DeviceInfo": {
                    "DeviceId": "synthetic-e30",
                    "Model": "DM-NVX-E30",
                    "DeviceVersion": "6.0.4835.00027",
                }
            }
        },
        {
            "Device": {
                "DeviceSpecific": {
                    "DeviceMode": "Transmitter",
                    "DeviceReady": 1,
                    "ActiveVideoSource": "HDMI1",
                    "ActiveAudioSource": "HDMI1",
                }
            }
        },
        {
            "Device": {
                "AudioVideoInputOutput": {
                    "Inputs": [
                        {
                            "Ports": [
                                {
                                    "Uuid": "synthetic-e30-input",
                                    "IsSyncDetected": True,
                                    "HorizontalResolution": 3840,
                                    "VerticalResolution": 2160,
                                    "FramesPerSecond": 60,
                                }
                            ]
                        }
                    ],
                    "Outputs": [
                        {
                            "Ports": [
                                {
                                    "Uuid": "synthetic-e30-output",
                                    "ColorDepth": 8,
                                    "MaxColorDepth": 12,
                                    "IsSinkConnected": True,
                                    "Hdmi": {"Transmitting": True},
                                }
                            ]
                        }
                    ],
                }
            }
        },
        {
            "Device": {
                "StreamReceive": {
                    "Streams": [{"Status": "Stopped", "CodecReady": False}]
                }
            }
        },
        {
            "Device": {
                "StreamTransmit": {
                    "Streams": [
                        {
                            "UUID": "synthetic-e30-stream",
                            "Status": "Started",
                            "CodecReady": True,
                            "ActiveBitrate": 750,
                            "HorizontalResolution": 3840,
                            "VerticalResolution": 2160,
                            "FramesPerSecond": 60,
                        }
                    ]
                }
            }
        },
    )

    assert snapshot.device.model == "DM-NVX-E30"
    assert snapshot.device.firmware_version == "6.0.4835.00027"
    assert snapshot.device_ready is True
    assert snapshot.audio_mode is None
    assert snapshot.nax_audio_source is None
    assert snapshot.av_ports[0].sync_detected is True
    assert snapshot.av_ports[1].sink_connected is True
    assert snapshot.av_ports[1].transmitting is True
    assert snapshot.receive_streams[0].codec_ready is False
    assert snapshot.transmit_streams[0].bitrate_mbps == 750
    assert snapshot.transmit_streams[0].resolution == "3840x2160@60"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"Device": {}},
        {"Device": {"DeviceInfo": "invalid"}},
        {"Device": {"DeviceInfo": {"DeviceId": "id"}}},
    ],
)
def test_parse_rejects_invalid_identity(payload: dict[str, object]) -> None:
    """Reject responses that cannot provide stable registry identity."""
    with pytest.raises(NvxResponseError):
        NvxClient._parse_snapshot(payload, {})


def test_parse_limits_endpoint_collections() -> None:
    """Bound entities created from endpoint-controlled collections."""
    snapshot = NvxClient._parse_snapshot(
        {"Device": {"DeviceInfo": {"DeviceId": DEVICE_ID, "Model": "DM-NVX-350"}}},
        {},
        receive_payload={
            "Device": {
                "StreamReceive": {
                    "Streams": [{"UUID": f"stream-{index}"} for index in range(100)]
                }
            }
        },
    )

    assert len(snapshot.receive_streams) == 64


def test_client_configuration_url() -> None:
    """Expose the endpoint URL without exposing client internals."""
    client = NvxClient(MagicMock(), "192.0.2.1", "user", "password", verify_ssl=False)
    assert client.configuration_url == "https://192.0.2.1"


async def test_get_snapshot_logs_in_and_reads() -> None:
    """Log in once and issue only the documented reads."""
    info = {"Device": {"DeviceInfo": {"DeviceId": DEVICE_ID, "Model": "DM-NVX-350"}}}
    client = _client(
        [
            _response(200, cookies={"TRACKID": "track"}),
            _response(200, info),
            _response(200, {}),
            _response(200, {}),
            _response(200, {}),
            _response(200, {}),
        ],
        [_response(302, cookies={"userid": "user"})],
    )
    snapshot = await client.async_get_snapshot()
    assert snapshot.device.device_id == DEVICE_ID
    assert client._cookies == {"TRACKID": "track", "userid": "user"}


async def test_login_does_not_follow_redirects() -> None:
    """Keep the authentication bootstrap on the configured endpoint."""
    client = _client([_response(302)], [_response(200)])

    await client._async_login()

    assert client._session.get.call_args.kwargs["allow_redirects"] is False


async def test_get_snapshot_reauthenticates_once() -> None:
    """Reauthenticate and retry reads after an expired session."""
    info = {"Device": {"DeviceInfo": {"DeviceId": DEVICE_ID, "Model": "DM-NVX-350"}}}
    client = _client(
        [
            _response(200),
            _response(403),
            _response(200),
            _response(200, info),
            _response(200, {}),
            _response(200, {}),
            _response(200, {}),
            _response(200, {}),
        ],
        [_response(200, cookies={"userid": "old"}), _response(200)],
    )
    assert (await client.async_get_snapshot()).device.device_id == DEVICE_ID


@pytest.mark.parametrize("status", [401, 403])
async def test_login_rejects_bad_credentials(status: int) -> None:
    """Reject authentication response statuses."""
    client = _client([_response(200)], [_response(status)])
    with pytest.raises(NvxAuthenticationError):
        await client.async_get_snapshot()


async def test_login_rejects_unexpected_status() -> None:
    """Reject an unexpected login response."""
    client = _client([_response(200)], [_response(500)])
    with pytest.raises(NvxResponseError):
        await client.async_get_snapshot()


@pytest.mark.parametrize("method", ["get", "post"])
async def test_login_connection_error(method: str) -> None:
    """Translate transport errors during login."""
    get: list[object] = [ClientError()] if method == "get" else [_response(200)]
    post: list[object] = [ClientError()] if method == "post" else []
    client = _client(get, post)
    with pytest.raises(NvxConnectionError):
        await client.async_get_snapshot()


@pytest.mark.parametrize("status", [301, 302, 401, 403])
async def test_get_detects_expired_authentication(status: int) -> None:
    """Treat redirects and authorization failures as expired sessions."""
    client = _client([_response(status)])
    client._cookies = {"userid": "present"}
    with pytest.raises(NvxAuthenticationError):
        await client._async_get_json("/Device/Test")


async def test_get_rejects_http_error() -> None:
    """Reject an unexpected read status."""
    client = _client([_response(500)])
    client._cookies = {"userid": "present"}
    with pytest.raises(NvxResponseError):
        await client._async_get_json("/Device/Test")


async def test_get_translates_connection_error() -> None:
    """Translate read transport errors."""
    client = _client([ClientError()])
    client._cookies = {"userid": "present"}
    with pytest.raises(NvxConnectionError):
        await client._async_get_json("/Device/Test")


@pytest.mark.parametrize("error", [TypeError(), ValueError()])
async def test_get_rejects_invalid_json(error: Exception) -> None:
    """Reject malformed response bodies."""
    client = _client([_response(200, json_error=error)])
    client._cookies = {"userid": "present"}
    with pytest.raises(NvxResponseError):
        await client._async_get_json("/Device/Test")


async def test_get_rejects_non_object_json() -> None:
    """Reject JSON values that are not objects."""
    client = _client([_response(200, [])])
    client._cookies = {"userid": "present"}
    with pytest.raises(NvxResponseError):
        await client._async_get_json("/Device/Test")


async def test_get_rejects_oversized_json() -> None:
    """Bound memory consumed by a device response."""
    client = _client([_response(200, raw_body=b"x" * (2 * 1024 * 1024 + 1))])
    client._cookies = {"userid": "present"}

    with pytest.raises(NvxResponseError, match="oversized response"):
        await client._async_get_json("/Device/Test")


async def test_read_only_object_uses_allow_list() -> None:
    """Read an allow-listed documented path with an existing session."""
    client = _client([_response(200, {"Device": {"Preview": {}}})])
    client._cookies = {"userid": "present"}
    result = await client.async_get_read_only_object(NvxReadPath.PREVIEW)
    assert result == {"Device": {"Preview": {}}}


async def test_read_only_object_logs_in() -> None:
    """Authenticate before a documented object read when needed."""
    client = _client(
        [_response(200), _response(200, {"Device": {"StreamReceive": {}}})],
        [_response(200)],
    )
    result = await client.async_get_read_only_object(NvxReadPath.STREAM_RECEIVE)
    assert result == {"Device": {"StreamReceive": {}}}


async def test_read_only_object_reauthenticates() -> None:
    """Retry a documented object once after session expiry."""
    client = _client(
        [_response(403), _response(200), _response(200, {"Device": {}})],
        [_response(200)],
    )
    client._cookies = {"userid": "expired"}
    assert await client.async_get_read_only_object(NvxReadPath.STREAM_TRANSMIT) == {
        "Device": {}
    }
