import ipaddress
import socket
from urllib.parse import urlsplit


def validate_target_url(url: str) -> None:
    """Reject webhook targets that violate the URL security policy."""
    parsed = urlsplit(url)

    if parsed.scheme != "https":
        raise ValueError("Webhook target URL must use HTTPS.")

    if not parsed.hostname:
        raise ValueError("Webhook target URL must include a hostname.")

    if parsed.username or parsed.password:
        raise ValueError("Credentials in webhook URLs are not allowed.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid port in webhook URL.") from exc

    if port not in (None, 443):
        raise ValueError("Webhook target URL must use port 443.")

    hostname = parsed.hostname.rstrip(".").lower()

    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("Localhost URLs are not allowed.")

    try:
        addresses = socket.getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("Webhook target hostname could not be resolved.") from exc

    if not addresses:
        raise ValueError("Webhook target hostname has no IP addresses.")

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])

        if not ip.is_global:
            raise ValueError("Webhook target must resolve only to public IP addresses.")
