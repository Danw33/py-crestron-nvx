"""Synthetic configured-command discovery and no-replay transport tests."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from crestron_nvx import (
    NvxCapabilities,
    NvxConnectionError,
    NvxControlError,
    NvxControlUnsupported,
    NvxDisplayCommand,
    NvxResponseError,
)
from crestron_nvx.display import parse_display_commands

from .test_client import _response
from .test_control import BEFORE, ack, control_client


def payload(interface="Cec", input_enabled=True):
    return {
        "Device": {
            "CustomControlPortCommands": {
                "Version": "2.1.0",
                "AutomaticPowerControl": {
                    "AssociatedOutputsSupported": ["Output1"],
                    "AssociatedOutputs": {
                        "Output1": {
                            "ActivePortType": interface,
                            "ActivePort": "Port1",
                            "IsEnabled": True,
                        }
                    },
                },
                interface: {
                    "PortsSupported": ["Port1"],
                    "PortList": {
                        "Port1": {
                            "CommandsSupported": [
                                "PowerOn",
                                "PowerOff",
                                "InputControl",
                            ],
                            "PowerControlConfig": {
                                "IsInputControlEnabled": input_enabled
                            },
                            "CommandList": {
                                action: {
                                    "TransmitData": "configured-private-command",
                                    "Format": "Hex",
                                    "IsCustomCmd": False,
                                    "Type": "ByName"
                                    if interface == "Infrared"
                                    else "None",
                                }
                                for action in ("PowerOn", "PowerOff", "InputControl")
                            },
                        }
                    },
                },
            }
        }
    }


@pytest.mark.parametrize("interface", ["Cec", "Serial", "Infrared"])
@pytest.mark.parametrize("enabled", [True, False, 1, 0, None, "true"])
def test_observed_commands(interface, enabled):
    commands = parse_display_commands(payload(interface, enabled))
    assert len(commands) == (
        3 if enabled is True or (type(enabled) is int and enabled == 1) else 2
    )
    assert commands[0] == NvxDisplayCommand("Output1", "PowerOn", interface, "Port1")
    assert "configured-private-command" not in repr(commands)
    assert (
        NvxCapabilities.from_snapshot(
            BEFORE, display_commands=commands
        ).display_commands
        == commands
    )


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"Device": None},
        {"Device": {"CustomControlPortCommands": "unsupported"}},
    ],
)
def test_invalid_root(data):
    assert not parse_display_commands(data)


@pytest.mark.parametrize(
    "path,value",
    [
        (["Version"], None),
        (["Version"], "2.0.1"),
        (["Version"], "bad"),
        (["AutomaticPowerControl", "AssociatedOutputsSupported"], None),
        (["AutomaticPowerControl", "AssociatedOutputsSupported"], []),
        (["AutomaticPowerControl", "AssociatedOutputs", "Output1"], None),
        (["AutomaticPowerControl", "AssociatedOutputs", "Output1", "IsEnabled"], False),
        (
            ["AutomaticPowerControl", "AssociatedOutputs", "Output1", "IsEnabled"],
            "true",
        ),
        (
            ["AutomaticPowerControl", "AssociatedOutputs", "Output1", "ActivePortType"],
            "Unknown",
        ),
        (
            ["AutomaticPowerControl", "AssociatedOutputs", "Output1", "ActivePort"],
            "Port1.bad",
        ),
        (["Cec", "PortsSupported"], None),
        (["Cec", "PortsSupported"], []),
        (["Cec", "PortList", "Port1", "CommandsSupported"], None),
        (["Cec", "PortList", "Port1", "CommandsSupported"], []),
    ],
)
def test_missing_or_unsupported_mapping(path, value):
    data = payload()
    target = data["Device"]["CustomControlPortCommands"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert not parse_display_commands(data)


@pytest.mark.parametrize(
    "interface,field,value",
    [
        ("Cec", "TransmitData", ""),
        ("Cec", "TransmitData", 1),
        ("Cec", "TransmitData", "x" * 129),
        ("Serial", "Format", "Unknown"),
        ("Cec", "IsCustomCmd", None),
        ("Cec", "IsCustomCmd", "false"),
        ("Infrared", "Type", "None"),
    ],
)
def test_empty_and_ambiguous_command_templates(interface, field, value):
    data = payload(interface)
    data["Device"]["CustomControlPortCommands"][interface]["PortList"]["Port1"][
        "CommandList"
    ]["PowerOn"][field] = value
    assert [item.action for item in parse_display_commands(data)] == [
        "PowerOff",
        "InputControl",
    ]


def test_multiple_outputs_and_hostile_keys():
    data = payload()
    root = data["Device"]["CustomControlPortCommands"]
    auto = root["AutomaticPowerControl"]
    auto["AssociatedOutputsSupported"] += ["Output2", "Output1.bad"]
    auto["AssociatedOutputs"]["Output2"] = deepcopy(
        auto["AssociatedOutputs"]["Output1"]
    )
    auto["AssociatedOutputs"]["Output1.bad"] = deepcopy(
        auto["AssociatedOutputs"]["Output1"]
    )
    auto["AssociatedOutputs"]["Output2"]["ActivePort"] = "Port2"
    root["Cec"]["PortsSupported"].append("Port2")
    root["Cec"]["PortList"]["Port2"] = deepcopy(root["Cec"]["PortList"]["Port1"])
    commands = parse_display_commands(data)
    assert len(commands) == 6
    assert {item.port_id for item in commands if item.output_id == "Output2"} == {
        "Port2"
    }


def client_for(interface="Cec", response=None):
    client = control_client(
        response or _response(200, ack(path="Device.CustomControlPortCommands")),
        [BEFORE],
    )
    client._async_get_read_only_object = AsyncMock(return_value=payload(interface))
    return client


@pytest.mark.parametrize("interface", ["Cec", "Serial", "Infrared"])
@pytest.mark.parametrize("action", ["PowerOn", "PowerOff", "InputControl"])
async def test_exact_payload_current_mapping_no_readback(interface, action):
    client = client_for(interface)
    await client.async_send_display_command(
        "Output1", action, expected_device_id="test"
    )
    call = client._session.post.call_args
    assert call.kwargs["json"] == {
        "Device": {
            "CustomControlPortCommands": {
                interface: {
                    "PortList": {"Port1": {"CommandList": {action: {"Test": True}}}}
                }
            }
        }
    }
    assert call.kwargs["allow_redirects"] is False
    client._session.post.assert_called_once()
    client._async_get_snapshot.assert_awaited_once()
    client._async_get_read_only_object.assert_awaited_once()


@pytest.mark.parametrize(
    "suffix,prop",
    [
        ("", "Cec"),
        (".Cec", "PortList"),
        (".Cec.PortList", "Port1"),
        (".Cec.PortList.Port1", "CommandList"),
        (".Cec.PortList.Port1.CommandList", "PowerOn"),
        (".Cec.PortList.Port1.CommandList.PowerOn", "Test"),
        (".Cec.PortList.Port1.CommandList.PowerOn.Test", None),
    ],
)
async def test_relevant_ack(suffix, prop):
    client = client_for(
        response=_response(
            200, ack(path="Device.CustomControlPortCommands" + suffix, prop=prop)
        )
    )
    await client.async_send_display_command("Output1", "PowerOn")


@pytest.mark.parametrize(
    "output,action",
    [
        ("Output0", "PowerOn"),
        ("Output1.bad", "PowerOn"),
        (None, "PowerOn"),
        ("Output1", "Reboot"),
        ("Output1", {}),
        ("Output1", "poweron"),
    ],
)
async def test_invalid_arguments_no_io(output, action):
    client = client_for()
    with pytest.raises(ValueError):
        await client.async_send_display_command(output, action)
    client._async_get_snapshot.assert_not_awaited()


@pytest.mark.parametrize("identity", ["", " ", 5])
async def test_invalid_identity(identity):
    client = client_for()
    with pytest.raises(ValueError):
        await client.async_send_display_command(
            "Output1", "PowerOn", expected_device_id=identity
        )
    client._async_get_snapshot.assert_not_awaited()


async def test_identity_mismatch_and_non_nvx():
    client = client_for()
    with pytest.raises(NvxControlError):
        await client.async_send_display_command(
            "Output1", "PowerOn", expected_device_id="other"
        )
    client._async_get_read_only_object.assert_not_awaited()
    client._async_get_snapshot = AsyncMock(
        return_value=replace(BEFORE, device=replace(BEFORE.device, model="CP4"))
    )
    with pytest.raises(NvxControlUnsupported):
        await client.async_send_display_command("Output1", "PowerOn")
    client._session.post.assert_not_called()


async def test_optional_read_and_removed_command():
    client = client_for()
    assert len(await client.async_get_display_commands()) == 3
    client._async_get_read_only_object.side_effect = NvxResponseError
    assert await client.async_get_display_commands() == ()
    with pytest.raises(NvxControlUnsupported):
        await client.async_send_display_command("Output1", "PowerOn")
    client._session.post.assert_not_called()
    client._async_get_read_only_object.side_effect = NvxConnectionError
    with pytest.raises(NvxConnectionError):
        await client.async_get_display_commands()


@pytest.mark.parametrize(
    "response",
    [
        _response(403, {}),
        _response(200, ack(path="Device.CustomControlPortCommands", status=3)),
        _response(200, ack(path="Device.CustomControlPortCommands.Cec.PortList.Port2")),
        _response(
            200,
            ack(
                path="Device.CustomControlPortCommands.Cec.PortList.Port1.CommandList.PowerOff"
            ),
        ),
        _response(200, ack(path="Device.CustomControlPortCommands", prop="Serial")),
        _response(
            200,
            ack(
                path="Device.CustomControlPortCommands.Cec.PortList.Port1.CommandList.PowerOn",
                prop="TransmitData",
            ),
        ),
    ],
)
async def test_rejection_no_replay(response):
    client = client_for(response=response)
    with pytest.raises(NvxControlError):
        await client.async_send_display_command("Output1", "PowerOn")
    client._session.post.assert_called_once()


@pytest.mark.parametrize("error", [TimeoutError, asyncio.CancelledError])
async def test_timeout_cancel_no_replay(error):
    client = client_for()
    client._session.post.side_effect = error
    with pytest.raises(NvxConnectionError if error is TimeoutError else error):
        await client.async_send_display_command("Output1", "PowerOn")
    assert not client._io_lock.locked()
    client._session.post.assert_called_once()
