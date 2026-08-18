"""Shared pytest fixtures for the intercom skill test suite."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("intercom_skill", _INIT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["intercom_skill"] = _module
_spec.loader.exec_module(_module)

Intercom = _module.Intercom


@pytest.fixture
def skill(monkeypatch):
    s = Intercom.__new__(Intercom)
    s.log = MagicMock()
    s.skill_id = "ovos-skill-intercom.test"
    s.status = MagicMock()
    s._bus = MagicMock()
    s._settings = {}
    monkeypatch.setattr(Intercom, "lang", "en-us", raising=False)
    s.res_dir = str(Path(__file__).resolve().parents[1])
    s._lang_resources = {}
    # A fake server object so intent handlers that read self._server.port
    # don't need a real HTTPServer bound during unit tests.
    s._server = MagicMock()
    s._server.port = 12345
    return s
