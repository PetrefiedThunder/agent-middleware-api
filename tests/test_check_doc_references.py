"""Negative paths for the doc-reference gate.

The gate exists to catch prose that names a symbol the tree no longer defines.
A gate that only ever passes is not known to work, so these exercise the cases
that must fail and the exclusions that must not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "check_doc_references", ROOT / "scripts" / "check_doc_references.py"
)
assert _SPEC and _SPEC.loader
check_doc_references = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_doc_references)

_defined_names = check_doc_references._defined_names
_reference_resolves = check_doc_references._reference_resolves
_prose_spans = check_doc_references._prose_spans


def _names(**files: str) -> set[str]:
    return _defined_names({Path(name): source for name, source in files.items()})


def test_prose_alone_cannot_define_a_name():
    """A name surviving only in prose must not certify itself.

    This is the regression that matters: a renamed function whose old name
    lingers in a comment or string would otherwise vouch for the stale
    reference and the gate would report success.
    """
    names = _names(**{"mod.py": "# ``old_handler`` used to live here\nx = 1\n"})
    assert "old_handler" not in names
    assert not _reference_resolves("old_handler", names)


def test_string_literal_values_do_resolve():
    """Prose also names states and error codes that are real string values."""
    names = _names(**{"mod.py": 'STATE = "expired"\n'})
    assert _reference_resolves("expired", names)


def test_defined_symbols_resolve():
    names = _names(**{"mod.py": "class Wallet:\n    def charge(self):\n        pass\n"})
    assert _reference_resolves("Wallet", names)
    assert _reference_resolves("charge", names)
    assert _reference_resolves("Wallet.charge", names)


def test_dotted_reference_needs_both_halves():
    """An unrelated member of the same name must not satisfy a dotted ref."""
    names = _names(**{"mod.py": "def save():\n    pass\n"})
    assert _reference_resolves("save", names)
    assert not _reference_resolves("DeletedModel.save", names)


def test_unparseable_source_contributes_no_names():
    names = _names(**{"broken.py": "def (((\n"})
    assert not _reference_resolves("anything_at_all", names)
    # The filename itself still resolves; only parsed content is skipped.
    assert _reference_resolves("broken.py", names)


def test_prose_spans_survive_unparseable_source():
    assert _prose_spans("def (((\n") == []


@pytest.mark.parametrize("external", ["None", "True", "Origin", "pythonpath"])
def test_known_external_names_are_excluded(external):
    assert external in check_doc_references.KNOWN_EXTERNAL


def test_main_passes_on_the_real_tree():
    """The repository must be clean, so CI failure means a real regression."""
    assert check_doc_references.main([]) == 0
