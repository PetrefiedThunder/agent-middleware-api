#!/usr/bin/env python3
"""Vendor the site's webfonts from Google Fonts into ``site/fonts/``.

Run this only to add a family/weight or to refresh the files; the output is
committed, so a normal build never touches the network.

    python3 vendor_fonts.py            # rewrite fonts/ and fonts.css
    python3 vendor_fonts.py --check    # fail if the committed output is stale

Self-hosting removes two cross-origin handshakes from the critical path
(``fonts.googleapis.com`` for the CSS, ``fonts.gstatic.com`` for the files) and
lets ``vercel.json`` drop both hosts from the Content-Security-Policy.

Only the ``latin`` and ``latin-ext`` subsets are kept: the site is English, and
``latin-ext`` covers accented characters in an operator's name. Each face keeps
Google's ``unicode-range``, so a browser still downloads only the subsets the
page actually uses.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parent
FONT_DIR = SITE_ROOT / "fonts"
STYLESHEET = SITE_ROOT / "fonts.css"

# A modern desktop UA: the css2 API serves woff2 only to browsers it recognises,
# and returns bulkier ttf to anything it does not.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
# Must stay in step with the font stacks in styles.css.
FAMILIES = {
    "IBM Plex Mono": (400, 500, 600),
    "Libre Franklin": (700, 800),
    "Public Sans": (400, 500, 600),
}
WANTED_SUBSETS = ("latin", "latin-ext")
SLUGS = {
    "IBM Plex Mono": "ibm-plex-mono",
    "Libre Franklin": "libre-franklin",
    "Public Sans": "public-sans",
}
# Rendering order in the generated stylesheet.
FAMILY_ORDER = ("IBM Plex Mono", "Public Sans", "Libre Franklin")

STYLESHEET_HEADER = """/* ==========================================================================
   Self-hosted webfonts — same origin, no third-party request.

   GENERATED FILE. Do not edit by hand: run `python3 vendor_fonts.py` in
   site/ instead, and commit the result. The test suite asserts that every
   src below resolves to a committed file and that no file is orphaned;
   `vendor_fonts.py --check` additionally re-fetches upstream.

   Libre Franklin and Public Sans are variable fonts: Google returns one file
   per subset and varies the wght axis from font-weight, so several faces below
   deliberately share a src.
   ========================================================================== */
"""


class VendorError(RuntimeError):
    """Raised when upstream fonts cannot be vendored reproducibly."""


def _ssl_context() -> ssl.SSLContext:
    """Trust the standard CA-bundle overrides as well as the system store.

    Corporate and sandboxed networks terminate TLS at a proxy and publish their
    root via one of these variables; without it every fetch here fails.
    """

    for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        bundle = os.environ.get(variable, "").strip()
        if bundle and Path(bundle).is_file():
            return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(
            request, timeout=60, context=_ssl_context()
        ) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as error:
        raise VendorError(f"could not fetch {url}: {error}") from error


def discover_faces() -> list[dict]:
    """Return one descriptor per (family, weight, subset) face."""

    faces: list[dict] = []
    for family, weights in FAMILIES.items():
        spec = f"{family.replace(' ', '+')}:wght@{';'.join(str(w) for w in weights)}"
        css = _get(
            f"https://fonts.googleapis.com/css2?family={spec}&display=swap"
        ).decode("utf-8")
        # The API labels every @font-face with its subset in a preceding comment.
        for subset, block in re.findall(
            r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{.*?\})", css, re.S
        ):
            if subset not in WANTED_SUBSETS:
                continue
            faces.append(
                {
                    "family": family,
                    "weight": int(re.search(r"font-weight:\s*(\d+)", block).group(1)),
                    "subset": subset,
                    "url": re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1),
                    "range": re.search(r"unicode-range:\s*([^;]+);", block)
                    .group(1)
                    .strip(),
                }
            )
    missing = {
        (family, weight) for family, weights in FAMILIES.items() for weight in weights
    } - {(face["family"], face["weight"]) for face in faces}
    if missing:
        raise VendorError(f"upstream returned no face for: {sorted(missing)}")
    return faces


def download(faces: list[dict]) -> dict[str, bytes]:
    """Fetch every face and collapse byte-identical variable-font duplicates."""

    payloads: dict[str, bytes] = {}
    for face in faces:
        blob = _get(face["url"])
        if blob[:4] != b"wOF2":
            raise VendorError(f"{face['url']} is not woff2")
        face["sha"] = hashlib.sha256(blob).hexdigest()
        payloads[face["sha"]] = blob

    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for face in faces:
        grouped[face["sha"]].append(face)

    files: dict[str, bytes] = {}
    for sha, group in grouped.items():
        slug = SLUGS[group[0]["family"]]
        subset = group[0]["subset"]
        # One file shared by several weights means a variable font; naming it
        # after a single weight would be a lie.
        name = (
            f"{slug}-{subset}.woff2"
            if len({face["weight"] for face in group}) > 1
            else f"{slug}-{group[0]['weight']}-{subset}.woff2"
        )
        for face in group:
            face["file"] = name
        files[name] = payloads[sha]
    return files


def render_stylesheet(faces: list[dict]) -> str:
    ordered = sorted(
        faces,
        key=lambda face: (
            FAMILY_ORDER.index(face["family"]),
            face["weight"],
            face["subset"],
        ),
    )
    blocks = [
        f"/* {face['subset']} */\n"
        "@font-face {\n"
        f'  font-family: "{face["family"]}";\n'
        "  font-style: normal;\n"
        f"  font-weight: {face['weight']};\n"
        "  font-display: swap;\n"
        f'  src: url("/fonts/{face["file"]}") format("woff2");\n'
        f"  unicode-range: {face['range']};\n"
        "}\n"
        for face in ordered
    ]
    return STYLESHEET_HEADER + "\n" + "\n".join(blocks)


def vendor() -> tuple[dict[str, bytes], str]:
    faces = discover_faces()
    files = download(faces)
    return files, render_stylesheet(faces)


def write(files: dict[str, bytes], stylesheet: str) -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in FONT_DIR.glob("*.woff2"):
        if stale.name not in files:
            stale.unlink()
    for name, blob in files.items():
        (FONT_DIR / name).write_bytes(blob)
    STYLESHEET.write_text(stylesheet, encoding="utf-8")


def check(files: dict[str, bytes], stylesheet: str) -> list[str]:
    problems: list[str] = []
    on_disk = {path.name for path in FONT_DIR.glob("*.woff2")}
    for extra in sorted(on_disk - set(files)):
        problems.append(f"fonts/{extra} is committed but no longer referenced")
    for name, blob in files.items():
        path = FONT_DIR / name
        if not path.is_file():
            problems.append(f"fonts/{name} is missing")
        elif path.read_bytes() != blob:
            problems.append(f"fonts/{name} differs from upstream")
    if not STYLESHEET.is_file():
        problems.append("fonts.css is missing")
    elif STYLESHEET.read_text(encoding="utf-8") != stylesheet:
        problems.append("fonts.css is stale; re-run vendor_fonts.py")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed output matches upstream instead of rewriting it",
    )
    args = parser.parse_args(argv)
    try:
        files, stylesheet = vendor()
    except VendorError as error:
        print(f"font vendoring failed: {error}", file=sys.stderr)
        return 2

    if args.check:
        problems = check(files, stylesheet)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0

    write(files, stylesheet)
    total = sum(len(blob) for blob in files.values())
    print(f"vendored {len(files)} files ({total:,} bytes) into {FONT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
