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


def _patch_fake_scan(monkeypatch, found):
    """Patches discover_peer()'s Zeroconf/ServiceBrowser dependencies
    so a scan completes instantly with a pre-populated result set,
    instead of doing a real ~3s mDNS scan."""
    class FakeZC:
        def close(self):
            pass

    class FakeBrowser:
        def __init__(self, zc, service_type, listener):
            listener.found.update(found)

    monkeypatch.setattr(mod, "Zeroconf", FakeZC)
    monkeypatch.setattr(mod, "ServiceBrowser", FakeBrowser)


def test_discover_peer_exact_match(monkeypatch):
    _patch_fake_scan(monkeypatch, {"bedroom": {"ip": "192.168.1.50", "port": 5000}})
    assert mod.discover_peer("bedroom", timeout=0) == {"ip": "192.168.1.50", "port": 5000}


def test_discover_peer_matches_with_leading_article(monkeypatch):
    """Regression test, caught via live testing on real hardware, not
    a unit test guess: Padatious's {target} slot captures whatever
    follows 'to ' literally, so 'send a message to THE bedroom'
    yields target='the bedroom', but a device only ever advertises
    its bare configured name ('bedroom'). See DEVELOPMENT.md
    'Article-stripping via substring match'."""
    _patch_fake_scan(monkeypatch, {"bedroom": {"ip": "192.168.1.50", "port": 5000}})
    assert mod.discover_peer("the bedroom", timeout=0) == {"ip": "192.168.1.50", "port": 5000}


def test_discover_peer_no_match_returns_none(monkeypatch):
    _patch_fake_scan(monkeypatch, {"bedroom": {"ip": "192.168.1.50", "port": 5000}})
    assert mod.discover_peer("kitchen", timeout=0) is None
