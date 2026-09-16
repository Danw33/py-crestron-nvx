"""Async, read-only client for the publicly documented DM NVX HTTPS API."""

import json
from collections.abc import Iterable, Mapping
from enum import StrEnum
from http.cookies import SimpleCookie
from itertools import islice
from typing import Any, Final

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from yarl import URL

from .models import NvxAvPort, NvxDeviceInfo, NvxSnapshot, NvxStream

_LOGIN_PATH: Final = "/userlogin.html"
_DEVICE_INFO_PATH: Final = "/Device/DeviceInfo"
_DEVICE_SPECIFIC_PATH: Final = "/Device/DeviceSpecific"
_AUDIO_VIDEO_INPUT_OUTPUT_PATH: Final = "/Device/AudioVideoInputOutput"
_STREAM_RECEIVE_PATH: Final = "/Device/StreamReceive"
_STREAM_TRANSMIT_PATH: Final = "/Device/StreamTransmit"
_REQUEST_TIMEOUT: Final = ClientTimeout(total=10)
_MAX_JSON_RESPONSE_BYTES: Final = 2 * 1024 * 1024
_MAX_COLLECTION_ITEMS: Final = 64
_READ_CHUNK_BYTES: Final = 64 * 1024


class NvxReadPath(StrEnum):
    """Documented object paths allowed by the read-only probe."""

    AUDIO_VIDEO_INPUT_OUTPUT = "/Device/AudioVideoInputOutput"
    STREAM_RECEIVE = "/Device/StreamReceive"
    STREAM_TRANSMIT = "/Device/StreamTransmit"
    PREVIEW = "/Device/Preview"


class NvxApiError(Exception):
    """Base error raised by the DM NVX client."""


class NvxAuthenticationError(NvxApiError):
    """Authentication failed or an authenticated session expired."""


class NvxConnectionError(NvxApiError):
    """The endpoint could not be reached."""


class NvxResponseError(NvxApiError):
    """The endpoint returned an unexpected response."""


class NvxClient:
    """Read-only client with a cookie store isolated per endpoint."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        username: str,
        password: str,
        *,
        verify_ssl: bool,
    ) -> None:
        """Initialize the client."""

        self._session = session
        self._base_url = URL.build(scheme="https", host=host)
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._cookies: dict[str, str] = {}

    @property
    def configuration_url(self) -> str:
        """Return the endpoint web interface URL."""

        return str(self._base_url)

    async def async_get_snapshot(self) -> NvxSnapshot:
        """Authenticate if needed and return one endpoint snapshot."""

        if not self._cookies:
            await self._async_login()
        try:
            info_payload = await self._async_get_json(_DEVICE_INFO_PATH)
            specific_payload = await self._async_get_json(_DEVICE_SPECIFIC_PATH)
        except NvxAuthenticationError:
            self._cookies.clear()
            await self._async_login()
            info_payload = await self._async_get_json(_DEVICE_INFO_PATH)
            specific_payload = await self._async_get_json(_DEVICE_SPECIFIC_PATH)
        av_payload = await self._async_get_optional_json(_AUDIO_VIDEO_INPUT_OUTPUT_PATH)
        receive_payload = await self._async_get_optional_json(_STREAM_RECEIVE_PATH)
        transmit_payload = await self._async_get_optional_json(_STREAM_TRANSMIT_PATH)
        return self._parse_snapshot(
            info_payload,
            specific_payload,
            av_payload,
            receive_payload,
            transmit_payload,
        )

    async def async_get_read_only_object(self, path: NvxReadPath) -> dict[str, Any]:
        """Read one allow-listed documented object, retrying authentication once."""

        if not self._cookies:
            await self._async_login()
        try:
            return await self._async_get_json(path)
        except NvxAuthenticationError:
            self._cookies.clear()
            await self._async_login()
            return await self._async_get_json(path)

    async def _async_login(self) -> None:
        """Establish an authenticated session without writing device state."""

        try:
            async with self._session.get(
                self._base_url.with_path(_LOGIN_PATH),
                allow_redirects=False,
                ssl=self._verify_ssl,
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                self._update_cookies(response)
            headers = {
                "Origin": str(self._base_url),
                "Referer": str(self._base_url.with_path(_LOGIN_PATH)),
            }
            async with self._session.post(
                self._base_url.with_path(_LOGIN_PATH),
                data={"login": self._username, "passwd": self._password},
                cookies=self._cookies,
                headers=headers,
                allow_redirects=False,
                ssl=self._verify_ssl,
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                self._update_cookies(response)
                if response.status in {401, 403}:
                    raise NvxAuthenticationError("Invalid credentials")
                if response.status not in {200, 302}:
                    raise NvxResponseError(f"Login returned HTTP {response.status}")
        except NvxApiError:
            raise
        except (ClientError, TimeoutError) as err:
            raise NvxConnectionError("Unable to connect to the endpoint") from err

    async def _async_get_json(self, path: str) -> dict[str, Any]:
        """Read JSON from one API path."""

        try:
            async with self._session.get(
                self._base_url.with_path(path),
                cookies=self._cookies,
                headers={"Referer": str(self._base_url)},
                allow_redirects=False,
                ssl=self._verify_ssl,
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                self._update_cookies(response)
                if response.status in {301, 302, 401, 403}:
                    raise NvxAuthenticationError("Session is not authenticated")
                if response.status != 200:
                    raise NvxResponseError(f"{path} returned HTTP {response.status}")
                payload = await _async_read_json(response, path)
        except NvxApiError:
            raise
        except (ClientError, TimeoutError) as err:
            raise NvxConnectionError("Unable to read from the endpoint") from err
        except (TypeError, ValueError, RecursionError) as err:
            raise NvxResponseError(f"{path} returned invalid JSON") from err
        if not isinstance(payload, dict):
            raise NvxResponseError(f"{path} returned an unexpected JSON value")
        return payload

    async def _async_get_optional_json(self, path: str) -> dict[str, Any]:
        """Read a model-specific object without failing the whole endpoint."""

        try:
            return await self._async_get_json(path)
        except NvxResponseError:
            return {}

    def _update_cookies(self, response: ClientResponse) -> None:
        """Store response cookies locally, including cookies from IP hosts."""

        cookie: SimpleCookie = response.cookies
        self._cookies.update({key: morsel.value for key, morsel in cookie.items()})

    @staticmethod
    def _parse_snapshot(
        info_payload: Mapping[str, Any],
        specific_payload: Mapping[str, Any],
        av_payload: Mapping[str, Any] | None = None,
        receive_payload: Mapping[str, Any] | None = None,
        transmit_payload: Mapping[str, Any] | None = None,
    ) -> NvxSnapshot:
        """Parse documented fields while tolerating model-specific omissions."""

        try:
            info = info_payload["Device"]["DeviceInfo"]
        except (KeyError, TypeError) as err:
            raise NvxResponseError("DeviceInfo payload is missing") from err
        if not isinstance(info, Mapping):
            raise NvxResponseError("DeviceInfo payload has an invalid shape")

        device_id = _optional_string(info.get("DeviceId")) or _optional_string(
            info.get("MacAddress")
        )
        model = _optional_string(info.get("Model"))
        if not device_id or not model:
            raise NvxResponseError("DeviceInfo has no stable identity or model")

        specific: Mapping[str, Any] = {}
        device_root = specific_payload.get("Device")
        if isinstance(device_root, Mapping):
            candidate = device_root.get("DeviceSpecific")
            if isinstance(candidate, Mapping):
                specific = candidate

        name = _optional_string(info.get("Name")) or model
        return NvxSnapshot(
            device=NvxDeviceInfo(
                device_id=device_id,
                name=name,
                model=model,
                serial_number=_optional_string(info.get("SerialNumber")),
                firmware_version=_optional_string(info.get("DeviceVersion")),
                mac_address=_optional_string(info.get("MacAddress")),
                manufacturer=_optional_string(info.get("Manufacturer")) or "Crestron",
                reboot_reason=_optional_string(info.get("RebootReason")),
            ),
            device_mode=_optional_string(specific.get("DeviceMode")),
            device_ready=_optional_bool(specific.get("DeviceReady")),
            active_audio_source=_optional_string(specific.get("ActiveAudioSource")),
            active_video_source=_optional_string(specific.get("ActiveVideoSource")),
            audio_mode=_optional_string(specific.get("AudioMode")),
            audio_source=_optional_string(specific.get("AudioSource")),
            video_source=_optional_string(specific.get("VideoSource")),
            nax_active_audio_source=_optional_string(
                specific.get("NaxActiveAudioSource")
            ),
            nax_audio_source=_optional_string(specific.get("NaxAudioSource")),
            auto_initiation_mode=_optional_bool(specific.get("AutoInitiationMode")),
            auto_input_routing_enabled=_optional_bool(
                specific.get("AutoInputRoutingEnabled")
            ),
            front_panel_lockout_enabled=_optional_bool(
                specific.get("IsFrontPanelLockoutEnabled")
            ),
            leds_enabled=_optional_bool(specific.get("LedsEnabled")),
            show_setup_information_on_osd=_optional_bool(
                specific.get("ShowSetupInformationOnOsd")
            ),
            av_ports=_parse_av_ports(av_payload or {}),
            receive_streams=_parse_streams(receive_payload or {}, "receive"),
            transmit_streams=_parse_streams(transmit_payload or {}, "transmit"),
            raw_device_specific=dict(specific),
        )


def _optional_string(value: object) -> str | None:
    """Return a non-empty string or None."""

    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_bool(value: object) -> bool | None:
    """Parse boolean values, including the observed firmware 6.0/7.1 0/1 form."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


def _optional_int(value: object) -> int | None:
    """Return an integer but never coerce a boolean."""

    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _object_collection(value: object) -> list[Mapping[str, Any]]:
    """Return mapping members from an API object collection."""

    members: Iterable[object]
    if isinstance(value, list):
        members = value
    elif isinstance(value, Mapping):
        members = value.values()
    else:
        return []
    return [
        item
        for item in islice(members, _MAX_COLLECTION_ITEMS)
        if isinstance(item, Mapping)
    ]


async def _async_read_json(response: ClientResponse, path: str) -> Any:
    """Read one JSON body without allowing an endpoint to exhaust memory."""

    body = bytearray()
    while len(body) <= _MAX_JSON_RESPONSE_BYTES:
        chunk = await response.content.read(
            min(_READ_CHUNK_BYTES, _MAX_JSON_RESPONSE_BYTES + 1 - len(body))
        )
        if not chunk:
            break
        body.extend(chunk)
    if len(body) > _MAX_JSON_RESPONSE_BYTES:
        raise NvxResponseError(f"{path} returned an oversized response")
    return json.loads(body)


def _nested_mapping(root: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    """Safely traverse nested mappings."""

    current: object = root
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def _parse_av_ports(payload: Mapping[str, Any]) -> tuple[NvxAvPort, ...]:
    """Parse input and output status from the observed 6.0 and 7.1 shapes."""

    root = _nested_mapping(payload, "Device", "AudioVideoInputOutput")
    ports: list[NvxAvPort] = []
    for direction, collection_name in (("input", "Inputs"), ("output", "Outputs")):
        for group_index, group in enumerate(
            _object_collection(root.get(collection_name))
        ):
            group_name = _optional_string(group.get("Name"))
            for port_index, port in enumerate(_object_collection(group.get("Ports"))):
                hdmi = port.get("Hdmi")
                if not isinstance(hdmi, Mapping):
                    hdmi = {}
                port_id = _optional_string(port.get("Uuid")) or (
                    f"{direction}_{group_index}_{port_index}"
                )
                port_name = (
                    _optional_string(hdmi.get("Name"))
                    or group_name
                    or f"{direction.title()} {group_index + 1}"
                )
                ports.append(
                    NvxAvPort(
                        port_id=port_id,
                        name=port_name,
                        direction=direction,
                        sync_detected=_optional_bool(port.get("IsSyncDetected")),
                        sink_connected=_optional_bool(port.get("IsSinkConnected")),
                        transmitting=_optional_bool(hdmi.get("Transmitting")),
                        hdcp_state=_optional_string(hdmi.get("HdcpState")),
                        horizontal_resolution=_optional_int(
                            port.get("HorizontalResolution")
                        ),
                        vertical_resolution=_optional_int(
                            port.get("VerticalResolution")
                        ),
                        frames_per_second=_optional_int(port.get("FramesPerSecond")),
                    )
                )
    return tuple(ports)


def _parse_streams(payload: Mapping[str, Any], direction: str) -> tuple[NvxStream, ...]:
    """Parse receive or transmit stream status from the observed 7.1 shape."""

    object_name = "StreamReceive" if direction == "receive" else "StreamTransmit"
    root = _nested_mapping(payload, "Device", object_name)
    streams: list[NvxStream] = []
    for index, stream in enumerate(_object_collection(root.get("Streams"))):
        stream_id = (
            _optional_string(stream.get("UUID"))
            or _optional_string(stream.get("Uuid"))
            or f"{direction}_{index}"
        )
        bitrate = _optional_int(stream.get("Bitrate"))
        if direction == "transmit":
            active_bitrate = _optional_int(stream.get("ActiveBitrate"))
            if active_bitrate is not None:
                bitrate = active_bitrate
        streams.append(
            NvxStream(
                stream_id=stream_id,
                direction=direction,
                status=_optional_string(stream.get("Status")),
                codec_ready=_optional_bool(stream.get("CodecReady")),
                bitrate_mbps=bitrate,
                horizontal_resolution=_optional_int(stream.get("HorizontalResolution")),
                vertical_resolution=_optional_int(stream.get("VerticalResolution")),
                frames_per_second=_optional_int(stream.get("FramesPerSecond")),
            )
        )
    return tuple(streams)
