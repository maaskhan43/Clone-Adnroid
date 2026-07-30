#!/usr/bin/env python3
"""Regression test for the V11 target-text preflight guard.

Proves:
  1. the corrupted 1470-1650 script is rejected by validate_blocks;
  2. a clean script passes;
  3. the bake-off CLI aborts (exit 2) on the corrupted script BEFORE any
     TTS/provider or ffmpeg call, using a dummy --script and bogus media
     paths that would fail loudly if reached.

Run: python tools/test_clonedub_v11_textguard.py
No TTS, no APIs.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from clonedub_v11_textguard import validate_blocks  # noqa: E402

CORRUPT = {"blocks": [
    {"id": "b000", "target_text_hi": "???? ??? ?????, ???? ???"},
    {"id": "b001", "target_text_hi": "??? ???? ???? ?? ???"},
]}
CLEAN = {"blocks": [
    {"id": "b000", "target_text_hi": "यहाँ ठीक है, यहीं शूट करते हैं।"},
    {"id": "b001", "target_text_hi": "Tumhari baaton mein kuchh galat hai.", "script": "roman"},
]}
EMPTY = {"blocks": [{"id": "b000", "target_text_hi": "   "}]}
SYMBOLS = {"blocks": [{"id": "b000", "target_text_hi": "!!! ... ??? ###"}]}


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    return cond


def main():
    ok = True
    ok &= check("corrupt mojibake rejected (2/2)", len(validate_blocks(CORRUPT["blocks"])) == 2)
    ok &= check("clean text accepted (0 bad)", len(validate_blocks(CLEAN["blocks"])) == 0)
    ok &= check("empty rejected", len(validate_blocks(EMPTY["blocks"])) == 1)
    ok &= check("symbols-only rejected", len(validate_blocks(SYMBOLS["blocks"])) == 1)
    ok &= check("roman blocked without config",
                len(validate_blocks([{"id": "x", "target_text_hi": "sirf roman line"}])) == 1)
    ok &= check("roman allowed via roman_ids",
                len(validate_blocks([{"id": "x", "target_text_hi": "sirf roman line"}], ["x"])) == 0)

    # bake-off CLI must abort on corrupt script before touching media/providers
    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "corrupt.json"
        sp.write_text(json.dumps(CORRUPT), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(HERE / "clonedub_v11_tts_bakeoff.py"),
             "--script", str(sp), "--original", "NO_SUCH_original.mp4",
             "--reference", "NO_SUCH_reference.mp4", "--music", "NO_SUCH_music.wav",
             "--providers", "eleven_v2", "--outdir", str(Path(td) / "out")],
            capture_output=True, text=True)
        aborted = proc.returncode == 2 and "PREFLIGHT REJECT" in proc.stdout
        # if it had reached media/provider work it would fail differently (not exit 2)
        ok &= check("bakeoff CLI aborts on corrupt script (exit 2, no provider/media call)", aborted)
        if not aborted:
            print("  rc=%s stdout=%r stderr=%r" % (proc.returncode, proc.stdout[-300:], proc.stderr[-300:]))

    print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
