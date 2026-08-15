#!/usr/bin/env python3
"""Fail when a comment or docstring names a symbol that no longer exists.

This gate exists because prose drifting from code is not cosmetic here. An
``AuditChainHeadModel`` docstring claimed concurrent audit writers serialized by
locking the row ``FOR UPDATE``; the service that owns the table does the
opposite (optimistic compare-and-set, chosen to avoid ``FOR UPDATE``). A
reviewer read the prose, trusted it, and wrote up a mechanism this system does
not implement. The same false claim had propagated to two other files before it
was caught.

No cheap check can catch that semantic contradiction. This one catches the
mechanically detectable half of the same failure: prose that names an
identifier the tree no longer defines, which is what a rename leaves behind.

The convention this relies on is the repo's own: real symbols are written in
double backticks inside comments and docstrings.

Usage:
  python scripts/check_doc_references.py          # exits non-zero on a dangling ref
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED_DIRS = ("app", "scripts", "migrations")

# ``identifier``, ``module.attr``, or ``func()`` appearing in prose.
BACKTICK_REF = re.compile(r"``([A-Za-z_][A-Za-z0-9_.]*)(?:\(\))?``")

# Names that legitimately appear in prose without being defined in this tree:
# builtins, common type names, and external identifiers we reference by name.
KNOWN_EXTERNAL = frozenset(
    {
        # Python builtins / typing vocabulary used descriptively in prose.
        "true", "false", "none", "null", "int", "str", "bool", "float",
        "dict", "list", "set", "bytes", "object", "Any", "Decimal", "datetime",
        # pytest/setuptools configuration key, not a repo symbol.
        "pythonpath",
        # MCP SDK class referenced when describing what the SDK transport does.
        "StreamableHTTPSessionManager",
    }
)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for directory in SCANNED_DIRS:
        files.extend(sorted((ROOT / directory).rglob("*.py")))
    return files


def _prose_spans(source: str) -> list[tuple[int, str]]:
    """Return (lineno, text) for every comment and docstring in ``source``."""
    spans: list[tuple[int, str]] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                spans.append((token.start[0], token.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A file we cannot tokenize is a problem for ruff/mypy, not for us.
        return spans

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return spans
    doc_nodes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, doc_nodes):
            docstring = ast.get_docstring(node, clean=False)
            if docstring:
                spans.append((getattr(node, "lineno", 1), docstring))
    return spans


def _defined_names(sources: dict[Path, str]) -> set[str]:
    """Every identifier the tree uses outside of backticked prose.

    Deliberately broad: the goal is to flag names that appear *only* in prose,
    not to resolve each reference to its definition. A name used anywhere as
    real code counts as existing.
    """
    names: set[str] = set()
    for source in sources.values():
        # Strip backticked prose so a name that only ever appears in comments
        # cannot vouch for itself.
        stripped = BACKTICK_REF.sub(" ", source)
        names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stripped))
    return names


def main(argv: list[str] | None = None) -> int:
    _ = argv  # no options; the check is all-or-nothing by design
    files = _python_files()
    sources = {path: path.read_text(encoding="utf-8", errors="replace") for path in files}
    defined = _defined_names(sources)

    dangling: list[tuple[str, int, str]] = []
    checked = 0
    for path, source in sources.items():
        for lineno, text in _prose_spans(source):
            for match in BACKTICK_REF.finditer(text):
                reference = match.group(1)
                tail = reference.split(".")[-1]
                if not tail or tail in KNOWN_EXTERNAL or reference in KNOWN_EXTERNAL:
                    continue
                checked += 1
                if tail not in defined:
                    rel = path.relative_to(ROOT)
                    dangling.append((str(rel), lineno, reference))

    if dangling:
        print(
            f"{len(dangling)} comment/docstring reference(s) name a symbol that "
            "does not exist in this tree:",
            file=sys.stderr,
        )
        for rel, lineno, reference in dangling:
            print(f"  {rel}:{lineno}  ``{reference}``", file=sys.stderr)
        print(
            "\nRename the reference to the current symbol, or add it to "
            "KNOWN_EXTERNAL in this script if it names something outside the "
            "repo.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Doc references OK: {checked} backticked reference(s) across "
        f"{len(files)} file(s) all resolve."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
