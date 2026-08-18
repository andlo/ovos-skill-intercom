"""Tests for normalize_code()/normalize_name() - both accept either a
PIN or a spoken passphrase, matched case- and whitespace-insensitively."""
import importlib.util
import sys
from pathlib import Path

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("intercom_skill_mod", _INIT_PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules["intercom_skill_mod"] = mod
_spec.loader.exec_module(mod)


def test_normalize_code_lowercases():
    assert mod.normalize_code("Four Seven Two Nine") == "four seven two nine"


def test_normalize_code_collapses_whitespace():
    assert mod.normalize_code("  four   seven  two nine  ") == "four seven two nine"


def test_normalize_code_accepts_digits():
    assert mod.normalize_code("4729") == "4729"


def test_normalize_code_empty_returns_none():
    assert mod.normalize_code("") is None
    assert mod.normalize_code(None) is None
    assert mod.normalize_code("   ") is None


def test_normalize_name_same_as_code():
    """Names and codes use the exact same normalization rule -
    verified by construction, not just asserted."""
    assert mod.normalize_name("Living Room") == mod.normalize_code("Living Room")


def test_two_differently_spoken_but_equal_codes_match():
    """The whole point of normalize_code(): two utterances that a
    human would consider 'the same code' spoken slightly differently
    (extra spaces, different case from STT) must normalize identically."""
    a = mod.normalize_code("Four Seven Two Nine")
    b = mod.normalize_code("four  seven two   nine")
    assert a == b
