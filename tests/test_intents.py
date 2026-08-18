"""Tests for the intent handlers - discovery, sending, and receiving
are mocked here (covered separately in test_wire_protocol.py and
test_service_discovery.py); these tests focus on the intent-level
control flow and dialog selection."""
from unittest.mock import MagicMock


def _msg(**data):
    m = MagicMock()
    m.data = data
    return m


def test_set_intercom_code_valid(skill):
    skill.speak_dialog = MagicMock()
    skill.handle_set_intercom_code(_msg(code="four seven two nine"))
    assert skill.settings["intercom_code"] == "four seven two nine"
    skill.speak_dialog.assert_called_once_with("code_set")


def test_set_intercom_code_empty(skill):
    skill.speak_dialog = MagicMock()
    skill.handle_set_intercom_code(_msg(code=""))
    assert "intercom_code" not in skill.settings
    skill.speak_dialog.assert_called_once_with("code_not_understood")


def test_set_intercom_name_valid(skill, monkeypatch):
    skill.speak_dialog = MagicMock()
    skill._update_advertisement = MagicMock()
    skill.handle_set_intercom_name(_msg(name="Living Room"))
    assert skill.settings["intercom_name"] == "living room"
    skill._update_advertisement.assert_called_once()
    skill.speak_dialog.assert_called_once_with("name_set", {"name": "living room"})


def test_send_message_blocked_without_own_name(skill):
    skill.speak_dialog = MagicMock()
    skill.settings.update({"intercom_code": "1234"})
    skill.handle_send_message(_msg(target="bedroom"))
    skill.speak_dialog.assert_called_once_with("own_name_not_set")


def test_send_message_blocked_without_own_code(skill):
    skill.speak_dialog = MagicMock()
    skill.settings.update({"intercom_name": "living room"})
    skill.handle_send_message(_msg(target="bedroom"))
    skill.speak_dialog.assert_called_once_with("own_code_not_set")


def test_send_message_target_not_found(skill, monkeypatch):
    skill.speak_dialog = MagicMock()
    skill.settings.update({"intercom_name": "living room", "intercom_code": "1234"})
    import intercom_skill
    monkeypatch.setattr(intercom_skill, "discover_peer", lambda target: None)
    skill.handle_send_message(_msg(target="bedroom"))
    skill.speak_dialog.assert_called_once_with("target_not_found", {"target": "bedroom"})


def test_send_message_full_success_flow(skill, monkeypatch):
    skill.settings.update({"intercom_name": "living room", "intercom_code": "1234"})
    skill.speak_dialog = MagicMock()
    skill.get_response = MagicMock(return_value="dinner is ready")
    import intercom_skill
    monkeypatch.setattr(intercom_skill, "discover_peer",
                         lambda target: {"ip": "127.0.0.1", "port": 9999})
    monkeypatch.setattr(intercom_skill, "send_message",
                         lambda *a, **kw: intercom_skill.STATUS_OK)
    skill.handle_send_message(_msg(target="bedroom"))
    skill.speak_dialog.assert_any_call("what_to_say")
    skill.speak_dialog.assert_any_call("message_sent")


def test_send_message_target_wrong_code(skill, monkeypatch):
    skill.settings.update({"intercom_name": "living room", "intercom_code": "1234"})
    skill.speak_dialog = MagicMock()
    skill.get_response = MagicMock(return_value="hello")
    import intercom_skill
    monkeypatch.setattr(intercom_skill, "discover_peer",
                         lambda target: {"ip": "127.0.0.1", "port": 9999})
    monkeypatch.setattr(intercom_skill, "send_message",
                         lambda *a, **kw: intercom_skill.STATUS_WRONG_CODE)
    skill.handle_send_message(_msg(target="bedroom"))
    skill.speak_dialog.assert_any_call("target_code_mismatch", {"target": "bedroom"})


def test_send_message_target_unreachable(skill, monkeypatch):
    skill.settings.update({"intercom_name": "living room", "intercom_code": "1234"})
    skill.speak_dialog = MagicMock()
    skill.get_response = MagicMock(return_value="hello")
    import intercom_skill
    monkeypatch.setattr(intercom_skill, "discover_peer",
                         lambda target: {"ip": "127.0.0.1", "port": 9999})
    monkeypatch.setattr(intercom_skill, "send_message", lambda *a, **kw: None)
    skill.handle_send_message(_msg(target="bedroom"))
    skill.speak_dialog.assert_any_call("target_unreachable", {"target": "bedroom"})


def test_send_message_no_text_from_get_response_aborts_silently(skill, monkeypatch):
    skill.settings.update({"intercom_name": "living room", "intercom_code": "1234"})
    skill.speak_dialog = MagicMock()
    skill.get_response = MagicMock(return_value=None)
    import intercom_skill
    monkeypatch.setattr(intercom_skill, "discover_peer",
                         lambda target: {"ip": "127.0.0.1", "port": 9999})
    send_spy = MagicMock()
    monkeypatch.setattr(intercom_skill, "send_message", send_spy)
    skill.handle_send_message(_msg(target="bedroom"))
    send_spy.assert_not_called()


def test_incoming_message_speaks_and_declines_reply(skill, monkeypatch):
    skill.speak_dialog = MagicMock()
    skill.speak = MagicMock()
    skill.ask_yesno = MagicMock(return_value="no")
    skill._handle_incoming_message(_msg(
        sender_name="bedroom", message="dinner's ready",
        sender_ip="127.0.0.1", reply_port=9999))
    skill.speak_dialog.assert_any_call("message_from", {"sender": "bedroom"})
    skill.speak.assert_called_once_with("dinner's ready")
    skill.ask_yesno.assert_called_once()


def test_incoming_message_reply_flow(skill, monkeypatch):
    skill.settings.update({"intercom_name": "bedroom", "intercom_code": "1234"})
    skill.speak_dialog = MagicMock()
    skill.speak = MagicMock()
    skill.ask_yesno = MagicMock(return_value="yes")
    skill.get_response = MagicMock(return_value="on my way")
    import intercom_skill
    monkeypatch.setattr(intercom_skill, "send_message",
                         lambda *a, **kw: intercom_skill.STATUS_OK)
    skill._handle_incoming_message(_msg(
        sender_name="living room", message="dinner's ready",
        sender_ip="127.0.0.1", reply_port=9999))
    skill.speak_dialog.assert_any_call("reply_sent")


def test_incoming_message_no_reply_address_skips_reply_prompt(skill):
    """If the sender didn't include a valid reply address, the
    receiver must not even offer to reply - there'd be nowhere to
    send it."""
    skill.speak_dialog = MagicMock()
    skill.speak = MagicMock()
    skill.ask_yesno = MagicMock()
    skill._handle_incoming_message(_msg(
        sender_name="bedroom", message="hi",
        sender_ip=None, reply_port=None))
    skill.ask_yesno.assert_not_called()
