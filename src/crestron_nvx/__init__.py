"""Unofficial async client for the publicly documented DM NVX REST API."""

from .capabilities import NvxCapabilities, is_nvx_model
from .client import (
    NvxApiError,
    NvxAuthenticationError,
    NvxClient,
    NvxConnectionError,
    NvxControlError,
    NvxControlUnsupported,
    NvxPermissionError,
    NvxPreviewUnavailable,
    NvxReadPath,
    NvxResponseError,
)
from .models import NvxAvPort, NvxDeviceInfo, NvxSnapshot, NvxStream
from .preview import NvxPreviewImage, NvxPreviewInfo
from .routing import is_valid_stream_location

__all__ = [
    "NvxApiError",
    "NvxAuthenticationError",
    "NvxAvPort",
    "NvxCapabilities",
    "NvxClient",
    "NvxConnectionError",
    "NvxControlError",
    "NvxControlUnsupported",
    "NvxDeviceInfo",
    "NvxPermissionError",
    "NvxPreviewImage",
    "NvxPreviewInfo",
    "NvxPreviewUnavailable",
    "NvxReadPath",
    "NvxResponseError",
    "NvxSnapshot",
    "NvxStream",
    "is_nvx_model",
    "is_valid_stream_location",
]
