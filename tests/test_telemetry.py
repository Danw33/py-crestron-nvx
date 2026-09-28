"""Synthetic regressions for firmware 7.1 telemetry observations."""

from copy import deepcopy

import pytest

from crestron_nvx.client import _parse_av_ports, _parse_streams


def test_ports_survive_uuid_churn_reordering_and_display_rename():
    """Identify physical slots even when every response regenerates all UUIDs."""
    inputs = [
        {
            "Name": f"input{i}",
            "Uuid": "old-group",
            "Ports": [
                {
                    "PortType": "Hdmi",
                    "Uuid": "old-port",
                    "IsSyncDetected": False,
                    "Hdmi": {"Name": f"INPUT {i + 1}"},
                },
                {"PortType": "Analog", "Uuid": "old-audio"},
            ],
        }
        for i in range(2)
    ]
    first = {
        "Device": {
            "AudioVideoInputOutput": {
                "Inputs": inputs,
                "Outputs": [
                    {
                        "Name": "output0",
                        "Ports": [
                            {
                                "PortType": "Hdmi",
                                "Uuid": "old-output",
                                "IsSinkConnected": False,
                                "Hdmi": {"Name": "OUTPUT 1", "Transmitting": False},
                            }
                        ],
                    }
                ],
            }
        }
    }
    second = deepcopy(first)
    root = second["Device"]["AudioVideoInputOutput"]
    root["Inputs"].reverse()
    for group in root["Inputs"] + root["Outputs"]:
        group["Uuid"] = "new-group"
        group["Ports"].reverse()
        for port in group["Ports"]:
            port["Uuid"] = "new-port"
            if "Hdmi" in port:
                port["Hdmi"]["Name"] = "User display label"
                port["IsSyncDetected"] = True
    before = {port.port_id: port for port in _parse_av_ports(first)}
    after = {port.port_id: port for port in _parse_av_ports(second)}
    assert before.keys() == after.keys()
    assert len(before) == 5
    assert not before["input_slot1_hdmi_0"].sync_detected
    assert after["input_slot1_hdmi_0"].sync_detected
    assert before["output_slot0_hdmi_0"].sink_connected is False
    assert before["output_slot0_hdmi_0"].resolution is None


def test_duplicate_slots_and_same_type_ports_have_distinct_keys():
    ports = _parse_av_ports(
        {
            "Device": {
                "AudioVideoInputOutput": {
                    "Inputs": [
                        {
                            "Name": "input0",
                            "Ports": [{"PortType": "Hdmi"}, {"PortType": "Hdmi"}],
                        },
                        {"Name": "input0", "Ports": [{"PortType": "Unknown"}]},
                        {"Name": "input2", "Ports": [{"PortType": "Hdmi"}]},
                    ]
                }
            }
        }
    )
    assert [port.port_id for port in ports] == [
        "input_index0_hdmi_0",
        "input_index0_hdmi_1",
        "input_index1_port0",
        "input_slot2_hdmi_0",
    ]


@pytest.mark.parametrize(
    "active,expected", [(686, 686), (0, 0), (None, None), (False, None), ("686", None)]
)
def test_reported_and_active_bitrates_are_independent(active, expected):
    stream = {"Bitrate": 750, "Status": "Stream started", "CodecReady": False}
    if active is not None:
        stream["ActiveBitrate"] = active
    result = _parse_streams(
        {"Device": {"StreamTransmit": {"Streams": [stream]}}}, "transmit"
    )[0]
    assert result.bitrate_mbps == 750
    assert result.active_bitrate_mbps == expected
    assert result.codec_ready is False


def test_stopped_defaults_and_receive_values_are_not_inferred():
    payload = {"Streams": [{"Bitrate": 10000, "Status": "Stream Stopped"}]}
    stopped = _parse_streams({"Device": {"StreamTransmit": payload}}, "transmit")[0]
    assert stopped.bitrate_mbps == 10000
    assert stopped.active_bitrate_mbps is None
    received = _parse_streams(
        {
            "Device": {
                "StreamReceive": {
                    "Streams": [
                        {"Bitrate": 0, "ActiveBitrate": 999, "Status": "Stream started"}
                    ]
                }
            }
        },
        "receive",
    )[0]
    assert received.bitrate_mbps == 0
    assert received.active_bitrate_mbps is None
