"""Conservative validation of advertised primary RTSP stream locations."""

from ipaddress import ip_address

from yarl import URL


def is_valid_stream_location(value: object) -> bool:
    """Accept credential-free RTSP URLs, without fetching or resolving them.

    IPv6 is deferred. Do not accept embedded credentials, queries, fragments,
    whitespace or control characters. Leave device stream credentials untouched.
    """
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        url = URL(value)
        host = url.host
        if (
            url.scheme != "rtsp"
            or not host
            or url.user is not None
            or url.password is not None
            or url.query_string
            or url.fragment
            or not url.path.strip("/")
            or (url.port is not None and not 1 <= url.port <= 65535)
            or ":" in host
            or "%" in host
            or "\\" in value
        ):
            return False
        try:
            address = ip_address(host)
        except ValueError:
            return host.lower() != "localhost" and all(
                part
                and all(
                    char.isascii() and (char.isalnum() or char == "-") for char in part
                )
                and not part.startswith("-")
                and not part.endswith("-")
                for part in host.rstrip(".").split(".")
            )
        return not (
            address.is_loopback
            or address.is_unspecified
            or address.is_multicast
            or address.is_link_local
        )
    except (ValueError, UnicodeError):
        return False
