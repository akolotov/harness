#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Append one validated meta/comment block to a review-comments Markdown file."""

import os
import re
import sys
import tempfile


MARKER_RE = re.compile(
    r'^<!-- (meta|comment):(begin|end) slug="([a-z0-9][a-z0-9-]*)" -->$'
)
FORBIDDEN_MARKERS = (
    "<!-- meta:begin",
    "<!-- meta:end",
    "<!-- comment:begin",
    "<!-- comment:end",
)


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def validate(text: str) -> set[str]:
    seen_slugs = set()
    open_block = None

    for line_no, line in enumerate(text.splitlines(), start=1):
        match = MARKER_RE.match(line)
        if not match:
            continue

        marker_kind, marker_side, marker_slug = match.groups()
        key = (marker_kind, marker_slug)

        if marker_side == "begin":
            if open_block is not None:
                fail(f"nested block at line {line_no}; open block is {open_block}")
            if marker_slug in seen_slugs:
                fail(f"duplicate slug={marker_slug}")
            seen_slugs.add(marker_slug)
            open_block = key
        elif open_block != key:
            fail(
                f"unmatched end marker at line {line_no}: "
                f"kind={marker_kind} slug={marker_slug}"
            )
        else:
            open_block = None

    if open_block is not None:
        fail(f"unclosed block: kind={open_block[0]} slug={open_block[1]}")

    return seen_slugs


def main() -> int:
    if len(sys.argv) != 4:
        fail(f"usage: {sys.argv[0]} <file-to-update> <meta|comment> <slug>", 2)

    file_to_update, kind, slug = sys.argv[1:4]

    if kind not in {"meta", "comment"}:
        fail("kind must be 'meta' or 'comment'", 2)

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        fail("slug must match ^[a-z0-9][a-z0-9-]*$", 2)

    body = sys.stdin.read()
    if not body.strip():
        fail("block body must not be empty", 2)

    for forbidden in FORBIDDEN_MARKERS:
        if forbidden in body:
            fail(f"block body must not contain marker fragment: {forbidden}", 2)

    existing = ""
    if os.path.exists(file_to_update):
        with open(file_to_update, "r", encoding="utf-8") as f:
            existing = f.read()

    seen_slugs = validate(existing)
    if slug in seen_slugs:
        fail(f"duplicate slug={slug}", 1)

    body = body.rstrip("\n") + "\n"
    block = (
        f'<!-- {kind}:begin slug="{slug}" -->\n'
        f"{body}"
        f'<!-- {kind}:end slug="{slug}" -->\n'
    )
    # Guarantee exactly one blank line between blocks, even when the existing
    # file does not end with a newline at all.
    if existing and not existing.endswith("\n"):
        existing += "\n"
    separator = "" if not existing or existing.endswith("\n\n") else "\n"
    new_text = existing + separator + block
    validate(new_text)

    parent = os.path.dirname(file_to_update)
    if parent:
        os.makedirs(parent, exist_ok=True)

    target_dir = parent or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".review-comment-block.", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp_path, file_to_update)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
