"""One-shot sending ("send a message to bedroom saying dinner is ready")
and re-advertising when the name changes in settings.json."""
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

LOCALE = Path(__file__).resolve().parents[1] / "locale"


def _msg(**data):
    m = MagicMock()
    m.data = data
    return m


@pytest.fixture
def ready(skill, monkeypatch):
    import intercom_skill
    skill.settings.update({"intercom_name": "living room", "intercom_code": "1234"})
    skill.speak_dialog = MagicMock()
    skill.get_response = MagicMock(return_value="asked text")
    monkeypatch.setattr(intercom_skill, "discover_peer",
                        lambda target: {"ip": "127.0.0.1", "port": 9999, "t": target})
    sent = MagicMock(return_value=intercom_skill.STATUS_OK)
    monkeypatch.setattr(intercom_skill, "send_message", sent)
    skill.sent = sent
    return skill


def test_one_shot_intent_sends_without_asking(ready):
    ready.handle_send_message_with_text(_msg(target="bedroom", message="dinner is ready"))
    ready.get_response.assert_not_called()
    args = ready.sent.call_args[0]
    assert args[4] == "dinner is ready"
    ready.speak_dialog.assert_called_once_with("message_sent")


def test_plain_intent_with_message_in_target_is_split(ready, monkeypatch):
    import intercom_skill
    seen = {}
    monkeypatch.setattr(intercom_skill, "discover_peer",
                        lambda t: seen.setdefault("t", t) and {"ip": "x", "port": 1})
    ready.handle_send_message(_msg(target="bedroom saying dinner is ready"))
    assert seen["t"] == "bedroom"
    ready.get_response.assert_not_called()
    assert ready.sent.call_args[0][4] == "dinner is ready"


def test_plain_intent_still_asks(ready):
    ready.handle_send_message(_msg(target="bedroom"))
    ready.speak_dialog.assert_any_call("what_to_say")
    assert ready.sent.call_args[0][4] == "asked text"


def test_danish_separator(ready, monkeypatch):
    monkeypatch.setattr(type(ready), "lang", "da-dk", raising=False)
    assert ready._split_target_and_text("alpha om at maden er klar") == \
        ("alpha", "maden er klar")
    assert ready._split_target_and_text("alpha og sig hejsa") == ("alpha", "hejsa")
    assert ready._split_target_and_text("soveværelset") == ("soveværelset", None)


def test_separator_must_not_be_the_whole_target(ready):
    # "saying" as the target itself is not a split
    assert ready._split_target_and_text("saying") == ("saying", None)


@pytest.mark.parametrize("lang", sorted(p.name for p in LOCALE.iterdir()))
def test_every_language_has_one_shot_files(lang):
    assert (LOCALE / lang / "send_message_with_text.intent").read_text().strip()
    assert (LOCALE / lang / "message_separator.voc").read_text().strip()


@pytest.mark.parametrize("intent", sorted(LOCALE.glob("*/*.intent")),
                         ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_adjacent_slots(intent):
    # ovos-workshop 9.x drops samples with adjacent slots (OVOS-INTENT-1)
    for line in intent.read_text().splitlines():
        assert not re.search(r"\}\s*\{", line), line


def test_settings_change_readvertises_on_new_name(skill):
    skill._update_advertisement = MagicMock()
    skill._advertised_name = "living room"
    skill.settings["intercom_name"] = "Kitchen"
    skill._on_settings_changed()
    skill._update_advertisement.assert_called_once()


def test_settings_change_ignores_same_name(skill):
    skill._update_advertisement = MagicMock()
    skill._advertised_name = "living room"
    skill.settings.update({"intercom_name": "Living Room", "intercom_code": "9"})
    skill._on_settings_changed()
    skill._update_advertisement.assert_not_called()


def test_settings_change_advertises_first_name(skill):
    skill._update_advertisement = MagicMock()
    skill.settings["intercom_name"] = "testing"
    skill._on_settings_changed()
    skill._update_advertisement.assert_called_once()
