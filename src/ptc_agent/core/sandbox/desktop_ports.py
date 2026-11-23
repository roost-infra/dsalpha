"""Daytona toolbox listeners that must never become shareable app previews."""

DAYTONA_NOVNC_PORT = 6080
_DESKTOP_PORTS = frozenset({5900, 5901, DAYTONA_NOVNC_PORT})


class DesktopPortReserved(ValueError):
    pass


def check_preview_port(channel: str, port: int) -> None:
    if channel == "daytona" and is_desktop_port(port):
        raise DesktopPortReserved("This port is reserved for the computer desktop.")


def is_desktop_port(port: int) -> bool:
    return port in _DESKTOP_PORTS
