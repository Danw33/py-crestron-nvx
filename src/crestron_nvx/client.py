"""Async monitoring and explicit controls for the documented DM NVX API."""

import asyncio
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from http.cookies import SimpleCookie
from itertools import islice
from typing import Any, Final, Literal

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from yarl import URL

from .models import NvxAvPort, NvxDeviceInfo, NvxSnapshot, NvxStream
from .preview import NvxPreviewImage, NvxPreviewInfo, jpeg_dimensions, parse_preview

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


class NvxPreviewUnavailable(NvxApiError):
    """Preview is unsupported, disabled or has no current image."""


class NvxControlError(NvxApiError):
    """A command was rejected or its effect could not be confirmed."""


class NvxControlUnsupported(NvxControlError):
    """The endpoint does not expose the requested control."""


class NvxPermissionError(NvxControlError):
    """A write was refused; do not assume read credentials are invalid."""


class NvxClient:
    """Client with explicit controls and a cookie store isolated per endpoint."""

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
        self._io_lock = asyncio.Lock()

    @property
    def configuration_url(self) -> str:
        """Return the endpoint web interface URL."""

        return str(self._base_url)

    async def async_set_leds_enabled(
        self, enabled: bool, *, expected_device_id: str | None = None
    ) -> NvxSnapshot:
        """Set only LEDs, once, and return observed state; never replay a POST.

        A timeout, cancellation or failed readback can leave the outcome unknown.
        The caller must reconcile by reading, not automatically repeat the write.
        """
        if type(enabled) is not bool:
            raise ValueError("LED state must be a boolean")
        if expected_device_id is not None and (
            not isinstance(expected_device_id, str) or not expected_device_id.strip()
        ):
            raise ValueError("Expected device identity must be a nonempty string")
        async with self._io_lock:
            before = await self._async_get_snapshot()
            if (
                expected_device_id is not None
                and before.device.device_id != expected_device_id
            ):
                raise NvxControlError(
                    "Endpoint identity does not match; no command sent"
                )
            if before.leds_enabled is None:
                raise NvxControlUnsupported("LED state is not available")
            if before.leds_enabled is enabled:
                return before
            await self._async_post_leds(enabled)
            # Only readbacks may be retried for a bounded propagation interval.
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(0.25)
                after = await self._async_get_snapshot()
                if after.device.device_id != before.device.device_id:
                    raise NvxControlError(
                        "Endpoint identity changed during verification"
                    )
                if after.leds_enabled is enabled:
                    return after
            raise NvxControlError("LED change could not be verified; outcome uncertain")

    async def _async_post_leds(self, enabled: bool) -> None:
        await self._async_post_control("LedsEnabled", enabled)

    async def async_set_video_source(
        self, source: str, *, expected_device_id: str | None = None
    ) -> NvxSnapshot:
        """Select a supported configured source; never alter automatic routing."""
        if not isinstance(source, str) or source not in {
            "None",
            "Input1",
            "Input2",
            "Stream",
        }:
            raise ValueError("Invalid video source")
        if expected_device_id is not None and (
            not isinstance(expected_device_id, str) or not expected_device_id.strip()
        ):
            raise ValueError("Expected device identity must be a nonempty string")
        async with self._io_lock:
            before = await self._async_get_snapshot()
            if (
                expected_device_id is not None
                and before.device.device_id != expected_device_id
            ):
                raise NvxControlError(
                    "Endpoint identity does not match; no command sent"
                )
            if source not in before.video_source_options:
                raise NvxControlUnsupported("Video source is not supported")
            if before.video_source == source:
                return before
            if before.auto_input_routing_enabled is not False:
                raise NvxControlUnsupported(
                    "Disable automatic input routing in the device web UI before selecting a source"
                )
            await self._async_post_control("VideoSource", source)
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(0.25)
                after = await self._async_get_snapshot()
                if after.device.device_id != before.device.device_id:
                    raise NvxControlError(
                        "Endpoint identity changed during verification"
                    )
                if after.video_source == source:
                    return after
            raise NvxControlError(
                "Video source change could not be verified; outcome uncertain"
            )

    async def async_set_audio_source(
        self, source: str, *, expected_device_id: str | None = None
    ) -> NvxSnapshot:
        """Select a supported primary audio source and verify configured state."""
        if not isinstance(source, str) or source not in {
            "AudioFollowsVideo",
            "Input1",
            "Input2",
            "AnalogAudio",
            "PrimaryStreamAudio",
        }:
            raise ValueError("Invalid audio source")
        if expected_device_id is not None and (
            not isinstance(expected_device_id, str) or not expected_device_id.strip()
        ):
            raise ValueError("Expected device identity must be a nonempty string")
        async with self._io_lock:
            before = await self._async_get_snapshot()
            if (
                expected_device_id is not None
                and before.device.device_id != expected_device_id
            ):
                raise NvxControlError(
                    "Endpoint identity does not match; no command sent"
                )
            if source not in before.audio_source_options:
                raise NvxControlUnsupported("Audio source is not supported")
            if before.audio_source == source:
                return before
            if before.auto_input_routing_enabled is not False:
                raise NvxControlUnsupported(
                    "Disable automatic input routing in the device web UI before selecting a source"
                )
            await self._async_post_control("AudioSource", source)
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(0.25)
                after = await self._async_get_snapshot()
                if after.device.device_id != before.device.device_id:
                    raise NvxControlError(
                        "Endpoint identity changed during verification"
                    )
                if after.audio_source == source:
                    return after
            raise NvxControlError(
                "Audio source change could not be verified; outcome uncertain"
            )

    async def async_reboot(self, *, expected_device_id: str | None = None) -> None:
        """Send one explicit reboot request after a fresh device identity check.

        The endpoint may disconnect before acknowledging the command. Never
        retry automatically or expect a readback from a restarting device.
        """
        if expected_device_id is not None and (
            not isinstance(expected_device_id, str) or not expected_device_id.strip()
        ):
            raise ValueError("Expected device identity must be a nonempty string")
        async with self._io_lock:
            before = await self._async_get_snapshot()
            if (
                expected_device_id is not None
                and before.device.device_id != expected_device_id
            ):
                raise NvxControlError(
                    "Endpoint identity does not match; no command sent"
                )
            if before.device.model.upper() not in {
                "DM-NVX-350",
                "DM-NVX-360",
                "DM-NVX-E30",
            }:
                raise NvxControlUnsupported("Reboot is not enabled for this model")
            await self._async_post_control(
                "Reboot", True, object_name="DeviceOperations"
            )

    async def _async_post_control(
        self,
        property_name: Literal["LedsEnabled", "VideoSource", "AudioSource", "Reboot"],
        value: bool | str,
        *,
        object_name: Literal["DeviceSpecific", "DeviceOperations"] = "DeviceSpecific",
    ) -> None:
        """Send a fixed, nonempty partial object; never expose arbitrary writes."""
        try:
            async with self._session.post(
                self._base_url.with_path("/Device"),
                json={"Device": {object_name: {property_name: value}}},
                cookies=self._cookies,
                headers={"Referer": str(self._base_url), "Origin": str(self._base_url)},
                allow_redirects=False,
                ssl=self._verify_ssl,
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                self._update_cookies(response)
                if response.status in {401, 403}:
                    # Read-only polling will independently determine whether
                    # session renewal/reauthentication is actually required.
                    raise NvxPermissionError("Control write refused")
                if response.status != 200:
                    raise NvxControlError(
                        "Unexpected control write response; outcome uncertain"
                    )
                payload = await _async_read_json(response, "/Device")
        except (ClientError, TimeoutError) as err:
            raise NvxConnectionError(
                "Control write interrupted; outcome uncertain"
            ) from err
        except (TypeError, ValueError, RecursionError) as err:
            raise NvxControlError(
                "Invalid control acknowledgement; outcome uncertain"
            ) from err
        _validate_control_result(payload, property_name, object_name=object_name)

    async def async_get_snapshot(self) -> NvxSnapshot:
        """Serialize status reads with preview reads and session renewal."""
        async with self._io_lock:
            return await self._async_get_snapshot()

    async def _async_get_snapshot(self) -> NvxSnapshot:
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
        """Serialize an allow-listed object read."""
        async with self._io_lock:
            return await self._async_get_read_only_object(path)

    async def _async_get_read_only_object(self, path: NvxReadPath) -> dict[str, Any]:
        """Read one allow-listed documented object, retrying authentication once."""

        if not self._cookies:
            await self._async_login()
        try:
            return await self._async_get_json(path)
        except NvxAuthenticationError:
            self._cookies.clear()
            await self._async_login()
            return await self._async_get_json(path)

    async def async_get_preview_info(self) -> NvxPreviewInfo:
        """Serialize capability discovery with other endpoint requests."""
        async with self._io_lock:
            return await self._async_get_preview_info()

    async def _async_get_preview_info(self) -> NvxPreviewInfo:
        """Discover optional preview support without downloading a frame."""
        try:
            payload = await self._async_get_read_only_object(NvxReadPath.PREVIEW)
        except NvxResponseError:
            return NvxPreviewInfo()
        return parse_preview(payload, self._base_url)

    async def async_get_preview(self) -> NvxPreviewImage:
        """Serialize an image read with other endpoint requests."""
        async with self._io_lock:
            return await self._async_get_preview()

    async def _async_get_preview(self) -> NvxPreviewImage:
        """Fetch one current JPEG with a bounded body and one authentication retry."""
        info = await self._async_get_preview_info()
        if not info.path:
            raise NvxPreviewUnavailable("No local preview is available")
        try:
            return await self._async_get_preview_image(info.path)
        except NvxAuthenticationError:
            self._cookies.clear()
            await self._async_login()
            return await self._async_get_preview_image(info.path)

    async def _async_get_preview_image(self, path: str) -> NvxPreviewImage:
        """Fetch only a validated path; never follow an image redirect."""
        try:
            async with self._session.get(
                self._base_url.with_path(path),
                cookies=self._cookies,
                headers={"Referer": str(self._base_url), "Accept": "image/jpeg"},
                allow_redirects=False,
                ssl=self._verify_ssl,
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                self._update_cookies(response)
                if response.status in {401, 403}:
                    raise NvxAuthenticationError("Preview session expired")
                if response.status in {404, 410, 204}:
                    raise NvxPreviewUnavailable("Preview image is unavailable")
                if response.status != 200 or response.content_type != "image/jpeg":
                    raise NvxResponseError("Invalid preview response")
                content = bytearray()
                while chunk := await response.content.read(_READ_CHUNK_BYTES):
                    content.extend(chunk)
                    if len(content) > _MAX_JSON_RESPONSE_BYTES:
                        raise NvxResponseError("Preview exceeds size limit")
                data = bytes(content)
                width, height = jpeg_dimensions(data)
                return NvxPreviewImage(data, width, height)
        except (ClientError, TimeoutError) as err:
            raise NvxConnectionError("Unable to fetch preview") from err
        except ValueError as err:
            raise NvxResponseError("Invalid JPEG preview") from err

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


def _validate_led_result(payload: object) -> None:
    """Validate the LED response using the shared acknowledgement parser."""
    _validate_control_result(payload, "LedsEnabled")


def _validate_control_result(
    payload: object,
    property_name: str,
    *,
    object_name: str = "DeviceSpecific",
) -> None:
    """Require relevant, explicit success and reject every reported failure."""
    actions = payload.get("Actions") if isinstance(payload, dict) else None
    if not isinstance(actions, list) or not actions or len(actions) > 64:
        raise NvxControlError("Missing control acknowledgement")
    relevant = False
    for action in actions:
        if not isinstance(action, dict) or action.get("Operation") != "SetPartial":
            raise NvxControlError("Unexpected control acknowledgement")
        results = action.get("Results")
        if not isinstance(results, list) or not results or len(results) > 64:
            raise NvxControlError("Missing control result")
        for result in results:
            if not isinstance(result, dict):
                raise NvxControlError("Invalid control result")
            status = result.get("StatusId")
            path = result.get("Path")
            prop = result.get("Property")
            object_path = f"Device.{object_name}"
            matches = (path == object_path and prop in (None, property_name)) or (
                path == f"{object_path}.{property_name}"
                and prop in (None, property_name)
            )
            if type(status) is not int or status != 0:
                if matches and type(status) is int and status in {-2, 3}:
                    raise NvxControlUnsupported("Control is read-only or unsupported")
                raise NvxControlError(
                    "Control change rejected or requires additional action"
                )
            relevant |= matches
    if not relevant:
        raise NvxControlError("Acknowledgement does not confirm requested control")


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
        groups = _object_collection(root.get(collection_name))
        # input0/output0 are physical slot designators, not HDMI display names.
        # Older shapes without a slot designator retain positional identity.
        slots = [
            match[1]
            if (
                match := re.fullmatch(
                    rf"{direction}(\d+)", str(group.get("Name", "")).lower()
                )
            )
            else None
            for group in groups
        ]
        slot_counts = Counter(slots)
        for group_index, group in enumerate(groups):
            group_name = _optional_string(group.get("Name"))
            slot = slots[group_index]
            group_key = (
                f"slot{slot}"
                if slot is not None and slot_counts[slot] == 1
                else f"index{group_index}"
            )
            type_counts: Counter[str] = Counter()
            for port_index, port in enumerate(_object_collection(group.get("Ports"))):
                hdmi = port.get("Hdmi")
                if not isinstance(hdmi, Mapping):
                    hdmi = {}
                port_type = str(port.get("PortType", "")).lower()
                if not port_type and hdmi:
                    port_type = "hdmi"
                if port_type in {
                    "hdmi",
                    "analog",
                    "audio",
                    "vga",
                    "bnc",
                    "displayport",
                }:
                    port_key = f"{port_type}_{type_counts[port_type]}"
                    type_counts[port_type] += 1
                else:
                    port_key = f"port{port_index}"
                # Firmware 7.1 can regenerate both group and port Uuids on
                # every GET. Never use them as persistent physical identity.
                port_id = f"{direction}_{group_key}_{port_key}"
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
        streams.append(
            NvxStream(
                stream_id=stream_id,
                direction=direction,
                status=_optional_string(stream.get("Status")),
                codec_ready=_optional_bool(stream.get("CodecReady")),
                bitrate_mbps=_optional_int(stream.get("Bitrate")),
                active_bitrate_mbps=(
                    _optional_int(stream.get("ActiveBitrate"))
                    if direction == "transmit"
                    else None
                ),
                horizontal_resolution=_optional_int(stream.get("HorizontalResolution")),
                vertical_resolution=_optional_int(stream.get("VerticalResolution")),
                frames_per_second=_optional_int(stream.get("FramesPerSecond")),
            )
        )
    return tuple(streams)
