"""Observed configured display commands, without retaining command strings."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import islice

DISPLAY_ACTIONS = ("PowerOn", "PowerOff", "InputControl")
_INTERFACES = ("Cec", "Serial", "Infrared")


def valid_output_id(value: object) -> bool:
    """Accept only documented numbered output dictionary keys."""
    return (
        isinstance(value, str)
        and re.fullmatch(r"Output[1-9][0-9]{0,2}", value) is not None
    )


@dataclass(frozen=True, slots=True)
class NvxDisplayCommand:
    """One configured command; output/action identifies its stable purpose."""

    output_id: str
    action: str
    interface: str
    port_id: str


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _enabled(value: object) -> bool:
    return value is True or (type(value) is int and value == 1)


def parse_display_commands(
    payload: Mapping[str, object],
) -> tuple[NvxDisplayCommand, ...]:
    """Fail closed on missing associations, empty templates or unknown encodings."""
    root = _mapping(_mapping(payload.get("Device")).get("CustomControlPortCommands"))
    version = root.get("Version")
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", version
    ):
        return ()
    if tuple(map(int, version.split("."))) < (2, 0, 2):
        return ()
    automatic = _mapping(root.get("AutomaticPowerControl"))
    outputs = _mapping(automatic.get("AssociatedOutputs"))
    supported = automatic.get("AssociatedOutputsSupported")
    if not isinstance(supported, list):
        return ()
    result = []
    for output_id, raw in islice(outputs.items(), 64):
        association = _mapping(raw)
        interface = association.get("ActivePortType")
        port_id = association.get("ActivePort")
        if (
            not valid_output_id(output_id)
            or output_id not in supported
            or not _enabled(association.get("IsEnabled"))
            or not isinstance(interface, str)
            or interface not in _INTERFACES
            or not isinstance(port_id, str)
            or not re.fullmatch(r"Port[1-9][0-9]{0,2}", port_id)
        ):
            continue
        section = _mapping(root.get(interface))
        ports = section.get("PortsSupported")
        if not isinstance(ports, list) or port_id not in ports:
            continue
        port = _mapping(_mapping(section.get("PortList")).get(port_id))
        commands = port.get("CommandsSupported")
        if not isinstance(commands, list):
            continue
        for action in DISPLAY_ACTIONS:
            if action not in commands:
                continue
            if action == "InputControl" and not _enabled(
                _mapping(port.get("PowerControlConfig")).get("IsInputControlEnabled")
            ):
                continue
            command = _mapping(_mapping(port.get("CommandList")).get(action))
            data = command.get("TransmitData")
            if not isinstance(data, str) or not data.strip() or len(data) > 128:
                continue
            if interface == "Infrared":
                if command.get("Type") not in ("ByName", "ByIndex", "Type12", "Type16"):
                    continue
            elif command.get("Format") not in ("Hex", "Ascii", "Base64Encoded", "Utf8"):
                continue
            if interface == "Cec" and not (
                type(command.get("IsCustomCmd")) is bool
                or (
                    type(command.get("IsCustomCmd")) is int
                    and command.get("IsCustomCmd") in (0, 1)
                )
            ):
                continue
            result.append(NvxDisplayCommand(output_id, action, interface, port_id))
    return tuple(result)
