#!/usr/bin/env python3
"""CloneDub V11: shared target-text validation.

One place that decides whether a block's target line is safe to send to
a TTS provider. Catches the failure that produced garbage 1470-1650s
previews: mojibake `?` text with no real letters.

Importable (validate_blocks) and runnable as a CLI preflight over any
script_blocks json. No TTS, no APIs.
"""

import argparse
import json
import re
import sys
from pathlib import Path

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
# a token counts as a spoken word only if it has a real letter (any script)
WORD = re.compile(r"[^\W\d_]", re.UNICODE)
REPLACEMENT_CHARS = "?�□"  # '?', unicode replacement, missing-glyph box
MIN_LETTER_RATIO = 0.30  # of non-space chars, at least this fraction must be letters


def validate_text(text, allow_roman=False):
    """Return (ok, reason). allow_roman lets a block be pure Latin (Hinglish)."""
    if text is None or not text.strip():
        return False, "empty or whitespace-only"
    stripped = text.strip()
    non_space = [c for c in stripped if not c.isspace()]
    letters = [c for c in non_space if WORD.match(c)]
    if not letters:
        return False, "no spoken letters (all punctuation/symbols)"
    repl = sum(stripped.count(c) for c in REPLACEMENT_CHARS)
    if repl and repl >= len(non_space) * 0.5:
        return False, "mostly replacement/mojibake chars (%d of %d)" % (repl, len(non_space))
    if len(letters) < len(non_space) * MIN_LETTER_RATIO:
        return False, ("letter ratio %.2f below %.2f (looks like mojibake/symbols)"
                       % (len(letters) / len(non_space), MIN_LETTER_RATIO))
    deva = DEVANAGARI.search(stripped)
    latin = LATIN.search(stripped)
    if not deva and not (allow_roman and latin):
        return False, ("no Devanagari characters (mark the block roman/Hinglish "
                       "in config to allow pure Latin)")
    return True, "ok"


def validate_blocks(blocks, roman_ids=None):
    """blocks: list of dicts with id + target_text_hi. Returns list of bad findings."""
    roman_ids = set(roman_ids or [])
    bad = []
    for b in blocks:
        bid = b.get("id", "?")
        allow_roman = bid in roman_ids or b.get("script") == "roman" or b.get("roman") is True
        text = b.get("target_text_hi") or b.get("text_hi") or ""
        ok, reason = validate_text(text, allow_roman=allow_roman)
        if not ok:
            bad.append({"id": bid, "reason": reason, "text_preview": (text or "")[:40]})
    return bad


def load_blocks(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc.get("blocks") or doc.get("segments") or []


def main():
    p = argparse.ArgumentParser(description="Preflight-validate target text in a "
                                            "script_blocks json (no TTS/APIs).")
    p.add_argument("--script", required=True, help="script_blocks json to validate")
    p.add_argument("--roman-ids", default="", help="comma-separated block ids allowed to be pure Latin")
    args = p.parse_args()
    blocks = load_blocks(args.script)
    bad = validate_blocks(blocks, [x for x in args.roman_ids.split(",") if x])
    total = sum(1 for b in blocks if (b.get("target_text_hi") or b.get("text_hi") or "").strip())
    if bad:
        print("REJECT: %d of %d blocks have invalid target text:" % (len(bad), total))
        for x in bad:
            print("  %s: %s | %r" % (x["id"], x["reason"], x["text_preview"]))
        return 1
    print("OK: all %d authored blocks have valid target text" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
