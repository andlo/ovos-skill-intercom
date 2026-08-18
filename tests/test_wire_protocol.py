"""Integration-style tests for the wire protocol: a real IntercomServer
bound to an ephemeral local port, exercised via real HTTP requests
over 127.0.0.1 - not mocked, since the actual value here is verifying
the real thread handoff (HTTP background thread -> self.bus.emit())
works, not just that individual functions return the right strings."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("intercom_skill_mod2", _INIT_PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules["intercom_skill_mod2"] = mod
_spec.loader.exec_module(mod)


def _fake_skill(code=None):
    skill = MagicMock()
    skill.settings = {"intercom_code": code} if code else {}
    skill.bus = MagicMock()
    return skill


def test_valid_code_accepted_and_bus_event_emitted():
    skill = _fake_skill(code="1234")
    server = mod.IntercomServer(skill)
    server.start()
    try:
        status = mod.send_message("127.0.0.1", server.port, "living room",
                                   "1234", "dinner is ready", 9999)
        assert status == mod.STATUS_OK
        assert skill.bus.emit.called
        emitted = skill.bus.emit.call_args[0][0]
        assert emitted.msg_type == mod.INCOMING_MESSAGE_BUS_EVENT
        assert emitted.data["message"] == "dinner is ready"
        assert emitted.data["sender_name"] == "living room"
        assert emitted.data["reply_port"] == 9999
    finally:
        server.stop()


def test_wrong_code_rejected_no_bus_event():
    skill = _fake_skill(code="1234")
    server = mod.IntercomServer(skill)
    server.start()
    try:
        status = mod.send_message("127.0.0.1", server.port, "x",
                                   "9999", "hello", 1)
        assert status == mod.STATUS_WRONG_CODE
        assert not skill.bus.emit.called
    finally:
        server.stop()


def test_no_code_set_reported_no_bus_event():
    skill = _fake_skill(code=None)
    server = mod.IntercomServer(skill)
    server.start()
    try:
        status = mod.send_message("127.0.0.1", server.port, "x",
                                   "anything", "hello", 1)
        assert status == mod.STATUS_NO_CODE_SET
        assert not skill.bus.emit.called
    finally:
        server.stop()


def test_code_matching_is_normalized_both_sides():
    """'Four Seven' (extra whitespace/case) from the sender must still
    match a receiver configured with 'four  seven' - normalize_code()
    is applied on both sides of the comparison, not just one."""
    skill = _fake_skill(code="four  seven")
    server = mod.IntercomServer(skill)
    server.start()
    try:
        status = mod.send_message("127.0.0.1", server.port, "x",
                                   "Four Seven", "hi", 1)
        assert status == mod.STATUS_OK
    finally:
        server.stop()


def test_unreachable_host_returns_none_not_a_status_string():
    """Port 1 has nothing listening - must return None (unreachable),
    a distinct case from any STATUS_* value."""
    status = mod.send_message("127.0.0.1", 1, "x", "code", "hi", 1, timeout=1)
    assert status is None
