"""Tests for the mDNS advertising/discovery helpers - build_service_info()
is pure and directly testable; _PeerCollectingListener is tested with
a mocked Zeroconf object (a real mDNS round-trip belongs in manual/
on-device testing, not a unit test)."""
import importlib.util
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("intercom_skill_mod3", _INIT_PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules["intercom_skill_mod3"] = mod
_spec.loader.exec_module(mod)


def test_build_service_info_shape():
    info = mod.build_service_info("living room", "192.168.1.50", 5000)
    assert info.type == mod.SERVICE_TYPE
    assert info.name == f"living room.{mod.SERVICE_TYPE}"
    assert info.port == 5000
    assert info.addresses == [socket.inet_aton("192.168.1.50")]


def test_build_service_info_carries_no_secret():
    """The code must never appear in the advertised service info -
    mDNS TXT records are broadcast in cleartext on the LAN, see
    DEVELOPMENT.md 'Wire protocol'."""
    info = mod.build_service_info("living room", "192.168.1.50", 5000)
    assert info.properties in ({}, None) or not any(
        b"code" in k for k in (info.properties or {}))


def test_peer_listener_strips_service_type_suffix():
    listener = mod._PeerCollectingListener()
    fake_zc = MagicMock()
    fake_info = MagicMock()
    fake_info.parsed_addresses.return_value = ["192.168.1.50"]
    fake_info.port = 5000
    fake_zc.get_service_info.return_value = fake_info

    full_name = f"living room.{mod.SERVICE_TYPE}"
    listener.add_service(fake_zc, mod.SERVICE_TYPE, full_name)

    assert listener.found[mod.normalize_name("living room")] == {
        "ip": "192.168.1.50", "port": 5000}


def test_peer_listener_ignores_service_with_no_addresses():
    listener = mod._PeerCollectingListener()
    fake_zc = MagicMock()
    fake_info = MagicMock()
    fake_info.parsed_addresses.return_value = []
    fake_zc.get_service_info.return_value = fake_info

    listener.add_service(fake_zc, mod.SERVICE_TYPE, f"x.{mod.SERVICE_TYPE}")
    assert listener.found == {}


def test_peer_listener_normalizes_matching():
    """A device advertised as 'Living Room' must be findable by a
    lookup for 'living room' (or vice versa) - matches
    normalize_name()'s case/whitespace-insensitive rule."""
    listener = mod._PeerCollectingListener()
    fake_zc = MagicMock()
    fake_info = MagicMock()
    fake_info.parsed_addresses.return_value = ["192.168.1.50"]
    fake_info.port = 5000
    fake_zc.get_service_info.return_value = fake_info

    listener.add_service(fake_zc, mod.SERVICE_TYPE, f"Living Room.{mod.SERVICE_TYPE}")
    assert "living room" in listener.found
