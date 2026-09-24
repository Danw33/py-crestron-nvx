"""Typed preview metadata and conservative parsing of public API fields."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import islice
from urllib.parse import unquote

from yarl import URL


@dataclass(frozen=True)
class NvxPreviewInfo:
    """Capability differs from enablement and current frame availability."""

    supported: bool = False
    enabled: bool = False
    path: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class NvxPreviewImage:
    """An in-memory JPEG; pixel data is excluded from representations."""

    content: bytes = field(repr=False)
    width: int
    height: int
    content_type: str = "image/jpeg"


def parse_preview(payload: Mapping[str, object], base_url: URL) -> NvxPreviewInfo:
    """Accept the documented object, never infer support from a string."""
    device = payload.get("Device")
    preview = device.get("Preview") if isinstance(device, Mapping) else None
    if not isinstance(preview, Mapping) or not isinstance(
        preview.get("IsPreviewOutputEnabled"), bool
    ):
        return NvxPreviewInfo()
    enabled = preview["IsPreviewOutputEnabled"]
    host = preview.get("HostPreviewImage", "Local")
    if not enabled or not isinstance(host, str) or host.casefold() != "local":
        return NvxPreviewInfo(supported=True, enabled=enabled)
    local = preview.get("LocalPreview", {})
    relative = local.get("RelativePath") if isinstance(local, Mapping) else None
    # Older object versions used LocalPreviewPath and an ImageList array.
    relative = relative or preview.get("LocalPreviewPath")
    entries = preview.get("ImageList", {})
    items = (
        list(islice(entries.values(), 64)) if isinstance(entries, Mapping) else entries
    )
    if not isinstance(items, list):
        return NvxPreviewInfo(True, True)
    # Stable ordering keeps firmware order for equal or unknown dimensions.
    for item in sorted(items[:64], key=_pixel_area, reverse=True):
        if not isinstance(item, Mapping) or item.get("IsImageAvailable") is False:
            continue
        name = item.get("Name")
        candidates = [item.get("FQDNPath"), item.get("IPv4Path")]
        if isinstance(relative, str) and isinstance(name, str):
            # Use the device's relative directory even when connected by a
            # hostname which differs from the advertised IPv4/FQDN aliases.
            candidates.insert(0, f"/{relative.strip('/')}/{name}")
        for candidate in candidates:
            path = safe_preview_path(candidate, base_url)
            if path:
                return NvxPreviewInfo(True, True, path)
    return NvxPreviewInfo(True, True)


def _pixel_area(item: object) -> int:
    """Rank numeric dimensions, without trusting malformed metadata."""
    if not isinstance(item, Mapping):
        return 0
    width, height = item.get("Width"), item.get("Height")
    if type(width) is not int or type(height) is not int:
        return 0
    if not (0 < width <= 8192 and 0 < height <= 8192):
        return 0
    area = width * height
    return area if area <= 16777216 else 0


def safe_preview_path(value: object, base_url: URL) -> str | None:
    """Reject external origins, credentials, queries and encoded traversal."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url = URL(value)
        if url.user is not None or url.query_string or url.fragment:
            return None
        if url.is_absolute() and url.origin() != base_url.origin():
            return None
        # Validate before URL normalization can remove dot segments.
        decoded = unquote(value)
        if "%" in decoded or "\\" in decoded or any(ord(c) < 32 for c in decoded):
            return None
        if any(part in {".", ".."} for part in decoded.split("/")):
            return None
        if not url.is_absolute() and (
            not value.startswith("/") or value.startswith("//")
        ):
            return None
        if not url.path.lower().endswith((".jpg", ".jpeg")):
            return None
        return url.path
    except ValueError:
        return None


def jpeg_dimensions(content: bytes) -> tuple[int, int]:
    """Read JPEG frame dimensions without decoding pixels or allocating a bitmap."""
    if not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
        raise ValueError("Invalid JPEG framing")
    offset = 2
    while offset + 4 <= len(content):
        if content[offset] != 0xFF:
            break
        marker = content[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        length = int.from_bytes(content[offset + 2 : offset + 4], "big")
        if length < 2 or offset + 2 + length > len(content):
            break
        if marker in {0xC0, 0xC1, 0xC2} and length >= 8:
            height = int.from_bytes(content[offset + 5 : offset + 7], "big")
            width = int.from_bytes(content[offset + 7 : offset + 9], "big")
            if 0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16777216:
                return width, height
            break
        offset += 2 + length
    raise ValueError("Invalid or excessive JPEG dimensions")
