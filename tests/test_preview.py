"""Synthetic preview capability, transport and hostile-response regressions."""

from copy import deepcopy

import pytest
from aiohttp import ClientError
from yarl import URL

from crestron_nvx import (
    NvxAuthenticationError,
    NvxConnectionError,
    NvxPreviewUnavailable,
    NvxResponseError,
)
from crestron_nvx.preview import jpeg_dimensions, parse_preview, safe_preview_path

from .test_client import _client, _response

BASE = URL("https://192.0.2.1")
# Invented JPEG header, used only to test dimension parsing (not pixel decoding).
JPEG = bytes.fromhex("ffd8ffc0000b080010002001011100ffd9")
PREVIEW = {
    "Device": {
        "Preview": {
            "IsPreviewOutputEnabled": True,
            "LocalPreview": {"RelativePath": "preview"},
            "ImageList": {
                "frame": {"Name": "synthetic.jpeg", "IsImageAvailable": True}
            },
        }
    }
}


@pytest.mark.parametrize("host", ["local", "Local", "LOCAL", "lOcAl"])
@pytest.mark.parametrize("as_list", [False, True])
def test_largest_local_preview(host, as_list):
    payload = deepcopy(PREVIEW)
    preview = payload["Device"]["Preview"]
    preview["HostPreviewImage"] = host
    preview["LocalPreview"]["RelativePath"] = "/preview"
    images = [
        {
            "Name": f"synthetic_{height}.jpeg",
            "Width": width,
            "Height": height,
            "IsImageAvailable": True,
        }
        for width, height in [(240, 135), (480, 270), (960, 540)]
    ]
    preview["ImageList"] = images if as_list else dict(enumerate(images))
    assert parse_preview(payload, BASE).path == "/preview/synthetic_540.jpeg"
    images[2]["IsImageAvailable"] = False
    assert parse_preview(payload, BASE).path == "/preview/synthetic_270.jpeg"
    images[1]["Name"] = "../invalid.jpeg"
    assert parse_preview(payload, BASE).path == "/preview/synthetic_135.jpeg"


@pytest.mark.parametrize("host", ["remote", "REMOTE", None, 1, {}])
def test_reject_nonlocal_host(host):
    payload = deepcopy(PREVIEW)
    payload["Device"]["Preview"]["HostPreviewImage"] = host
    assert parse_preview(payload, BASE).path is None


@pytest.mark.parametrize(
    "dimensions",
    [
        ({}, {}),
        (True, 20),
        ("960", "540"),
        (-1, 2),
        (9000, 1),
        (8192, 8192),
        (None, None),
        (0, 0),
    ],
)
def test_unknown_dimensions_rank_last(dimensions):
    payload = deepcopy(PREVIEW)
    payload["Device"]["Preview"]["ImageList"] = [
        {"Name": "unknown.jpeg", "Width": dimensions[0], "Height": dimensions[1]},
        {"Name": "known.jpeg", "Width": 240, "Height": 135},
    ]
    assert parse_preview(payload, BASE).path == "/preview/known.jpeg"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"Device": ""},
        {"Device": {"Preview": ""}},
        {"Device": {"Preview": {}}},
        {"Device": {"Preview": {"IsPreviewOutputEnabled": 1}}},
    ],
)
def test_unsupported(payload):
    assert not parse_preview(payload, BASE).supported


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "x" * 2049,
        "/preview/../secret.jpg",
        "/preview/%2e%2e/secret.jpg",
        "/preview/%252e%252e/x.jpg",
        "//evil.test/x.jpg",
        "https://evil.test/x.jpg",
        "http://192.0.2.1/x.jpg",
        "https://192.0.2.1:444/x.jpg",
        "https://user:pass@192.0.2.1/x.jpg",
        "/x.jpg?secret=yes",
        "/x.jpg#fragment",
        "/x\\y.jpg",
        "/x\ny.jpg",
        "x.jpg",
        "/Device/reboot",
        "https://[bad/x.jpg",
    ],
)
def test_reject_unsafe_paths(value):
    assert safe_preview_path(value, BASE) is None


def test_capability_states_and_versions():
    assert parse_preview(PREVIEW, BASE).path == "/preview/synthetic.jpeg"
    assert (
        safe_preview_path("https://192.0.2.1/preview/x.jpg", BASE) == "/preview/x.jpg"
    )
    for enabled, host in [(False, "Local"), (True, "Remote")]:
        info = parse_preview(
            {
                "Device": {
                    "Preview": {
                        "IsPreviewOutputEnabled": enabled,
                        "HostPreviewImage": host,
                    }
                }
            },
            BASE,
        )
        assert info.supported and info.path is None
    for images in [
        None,
        [],
        [None],
        [{"IsImageAvailable": False}],
        [{"Name": "x.jpg"}],
    ]:
        assert (
            parse_preview(
                {
                    "Device": {
                        "Preview": {"IsPreviewOutputEnabled": True, "ImageList": images}
                    }
                },
                BASE,
            ).path
            is None
        )
    info = parse_preview(
        {
            "Device": {
                "Preview": {
                    "IsPreviewOutputEnabled": True,
                    "LocalPreview": "",
                    "LocalPreviewPath": "thumbs",
                    "ImageList": [{"Name": "x.jpg"}],
                }
            }
        },
        BASE,
    )
    assert info.path == "/thumbs/x.jpg"


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"html",
        b"\xff\xd8\xff\xd9",
        b"\xff\xd8x123\xff\xd9",
        bytes.fromhex("ffd8ffe00001ffd9"),
        bytes.fromhex("ffd8ffe0ffff00ffd9"),
        bytes.fromhex("ffd8ffc0000b080000002001011100ffd9"),
    ],
)
def test_invalid_jpeg(body):
    with pytest.raises(ValueError):
        jpeg_dimensions(body)


def test_jpeg_dimensions():
    assert jpeg_dimensions(JPEG) == (32, 16)
    assert jpeg_dimensions(b"\xff\xd8\xff" + JPEG[2:]) == (32, 16)
    assert jpeg_dimensions(b"\xff\xd8\xff\xe0\x00\x02" + JPEG[2:]) == (32, 16)


async def test_fetch_and_cookie_isolation():
    response = _response(200, raw_body=JPEG)
    response.content_type = "image/jpeg"
    client = _client([_response(200, PREVIEW), response])
    client._cookies = {"session": "synthetic"}
    image = await client.async_get_preview()
    assert image.content == JPEG and (image.width, image.height) == (32, 16)
    assert "content=" not in repr(image)
    kwargs = client._session.get.call_args.kwargs
    assert kwargs["allow_redirects"] is False and kwargs["ssl"] is False
    assert client._session.get.call_args.args[0] == BASE.with_path(
        "/preview/synthetic.jpeg"
    )


@pytest.mark.parametrize("status", [404, 500])
async def test_missing_optional_object(status):
    client = _client([_response(status)])
    client._cookies = {"session": "synthetic"}
    assert not (await client.async_get_preview_info()).supported


async def test_v1_string_is_not_preview():
    client = _client([_response(200, {"Device": {"Preview": ""}})])
    client._cookies = {"session": "synthetic"}
    with pytest.raises(NvxPreviewUnavailable):
        await client.async_get_preview()
    assert client._session.get.call_count == 1


@pytest.mark.parametrize(
    "status,mime,body,error",
    [
        (404, "image/jpeg", JPEG, NvxPreviewUnavailable),
        (302, "image/jpeg", JPEG, NvxResponseError),
        (200, "text/html", JPEG, NvxResponseError),
        (200, "image/jpeg", b"not jpeg", NvxResponseError),
        (200, "image/jpeg", b"x" * (2 * 1024 * 1024 + 1), NvxResponseError),
    ],
)
async def test_bad_image(status, mime, body, error):
    response = _response(status, raw_body=body)
    response.content_type = mime
    client = _client([_response(200, PREVIEW), response])
    client._cookies = {"session": "synthetic"}
    with pytest.raises(error):
        await client.async_get_preview()


@pytest.mark.parametrize("failure", [ClientError(), TimeoutError()])
async def test_image_connection_failure(failure):
    client = _client([_response(200, PREVIEW), failure])
    client._cookies = {"session": "synthetic"}
    with pytest.raises(NvxConnectionError):
        await client.async_get_preview()


@pytest.mark.parametrize("final_status", [200, 401])
async def test_image_reauth_once(final_status):
    final = _response(final_status, raw_body=JPEG)
    final.content_type = "image/jpeg"
    client = _client(
        [_response(200, PREVIEW), _response(401), _response(200), final],
        [_response(200, cookies={"session": "renewed"})],
    )
    client._cookies = {"session": "old"}
    if final_status == 200:
        assert (await client.async_get_preview()).content == JPEG
    else:
        with pytest.raises(NvxAuthenticationError):
            await client.async_get_preview()
    assert client._session.post.call_count == 1
