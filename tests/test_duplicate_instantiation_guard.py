"""Regression tests for the module-level singleton guard against a
confirmed platform bug (OpenVoiceOS/ovos-core#887): plugin skills can
be instantiated twice at startup. This guard ensures only one
IntercomServer (one HTTP listener, one mDNS advertisement) is ever
active per process, self-healing by stopping the earlier instance's
server whenever a later duplicate initialize() runs."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("intercom_skill_mod4", _INIT_PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules["intercom_skill_mod4"] = mod
_spec.loader.exec_module(mod)

Intercom = mod.Intercom


def _make_bare_skill(monkeypatch):
    """A minimal Intercom instance suitable for calling initialize()/
    shutdown() directly - stubs out mDNS advertisement and bus event
    registration (neither is what this guard is testing) but uses a
    REAL IntercomServer/HTTPServer per call, so the test verifies the
    actual server lifecycle, not a mocked stand-in for it."""
    s = Intercom.__new__(Intercom)
    s.log = MagicMock()
    s.skill_id = "ovos-skill-intercom.test"
    s._bus = MagicMock()
    s._settings = {}
    monkeypatch.setattr(Intercom, "lang", "en-us", raising=False)
    s.add_event = MagicMock()
    s._update_advertisement = MagicMock()
    return s


@pytest.fixture(autouse=True)
def _reset_active_server():
    """Ensures module-level _active_server state doesn't leak between
    tests - each test starts from a clean None."""
    mod._active_server = None
    yield
    if mod._active_server is not None:
        try:
            mod._active_server.stop()
        except Exception:
            pass
    mod._active_server = None


def test_first_initialize_sets_active_server(monkeypatch):
    s = _make_bare_skill(monkeypatch)
    s.initialize()
    assert mod._active_server is s._server
    s.shutdown()


def test_second_initialize_stops_the_first_and_becomes_active(monkeypatch):
    """Simulates the real-world race from ovos-core#887: two Intercom
    instances both get initialize() called. Only the second's server
    should remain running afterward."""
    first = _make_bare_skill(monkeypatch)
    first.initialize()
    first_server = first._server
    first_port = first_server.port

    second = _make_bare_skill(monkeypatch)
    second.initialize()

    assert mod._active_server is second._server
    assert mod._active_server is not first_server

    # The first instance's HTTP server must actually be stopped, not
    # just orphaned - verified by confirming its port no longer
    # accepts connections.
    import socket
    with pytest.raises(OSError):
        conn = socket.create_connection(("127.0.0.1", first_port), timeout=1)
        conn.close()

    second.shutdown()


def test_shutdown_of_stale_instance_does_not_raise(monkeypatch):
    """A duplicate instance whose server was already stopped by a
    later initialize() must still shut down cleanly when the platform
    eventually calls shutdown() on it too - not every stale instance
    is guaranteed to be garbage collected without shutdown() being
    called on it first."""
    first = _make_bare_skill(monkeypatch)
    first.initialize()

    second = _make_bare_skill(monkeypatch)
    second.initialize()  # stops first's server, becomes active

    first.shutdown()  # must not raise even though its server is already stopped
    second.shutdown()


def test_shutdown_only_clears_active_server_if_it_is_still_self(monkeypatch):
    """The stale (first) instance's shutdown() must NOT clear
    _active_server, since by then it points at the second instance's
    server, not the first's."""
    first = _make_bare_skill(monkeypatch)
    first.initialize()

    second = _make_bare_skill(monkeypatch)
    second.initialize()

    first.shutdown()
    assert mod._active_server is second._server  # untouched by first's shutdown

    second.shutdown()
    assert mod._active_server is None
