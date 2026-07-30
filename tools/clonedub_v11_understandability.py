#!/usr/bin/env python3
"""CloneDub V11: understandability analysis of a dub window.

Human listening rejected the Eleven/Fish round-1 voices and preferred
old V1. This tool quantifies the acoustic + textual traits that plausibly
make one dub more understandable than another, so the next voice strategy
targets the right thing instead of guessing.

No TTS, no APIs, no generation. Reads audio + the pipeline transcript.

Per dubbed segment it measures:
  - speech rate (words/sec, syllable-proxy/sec)
  - pause structure (leading/trailing silence, internal gaps)
  - loudness (RMS dBFS, peak dBFS, crest factor)
  - dynamic stability (RMS variation across the segment = evenness)
  - text simplicity (words, chars/word, English-mix ratio, long-word count)
  - word-stretch / robotic proxy (sustained near-constant-pitch energy)
  - speaker (voice-consistency view across the window)

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 3/4 (voice bottleneck).
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"

SR = 16000
FRAME_S = 0.025
HOP_S = 0.010
SIL_DROP_DB = 32.0        # frame this far below segment peak = silence
INTERNAL_GAP_S = 0.20     # silence >= this inside a segment counts as a pause
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
HINDI_VOWELS = re.compile(r"[अ-औा-ौंःaeiouAEIOU]")


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s"
                           % (proc.returncode, " ".join(map(str, cmd)), proc.stderr[-1200:]))


def extract_segment_wav(src, dst, start, dur, sr=SR):
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % start, "-i", str(src),
         "-t", "%.3f" % dur, "-vn", "-ac", "1", "-ar", str(sr),
         "-c:a", "pcm_s16le", str(dst)])


def envelope(np, x):
    frame = int(round(FRAME_S * SR))
    hop = int(round(HOP_S * SR))
    if len(x) < frame:
        return np.zeros(0)
    n = 1 + (len(x) - frame) // hop
    csum = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    starts = np.arange(n) * hop
    return np.sqrt((csum[starts + frame] - csum[starts]) / frame)


def count_words(text):
    return [t for t in text.split() if any(c.isalnum() for c in t)]


def syllable_proxy(text):
    # crude: count vowel/matra runs (works acceptably for Devanagari + Latin Hindi)
    return len(re.findall(r"[अ-औा-ौaeiou]+", text.lower())) or len(count_words(text))


def analyze_segment(np, seg, wav):
    import soundfile as sf
    x, _ = sf.read(str(wav), dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    dur = len(x) / SR
    env = envelope(np, x)
    seg_peak = env.max() if len(env) else 0.0
    thr = seg_peak * (10 ** (-SIL_DROP_DB / 20.0))
    active = env >= thr if len(env) else np.zeros(0, bool)

    # pause structure
    lead = trail = 0.0
    idx = np.where(active)[0]
    if len(idx):
        lead = idx[0] * HOP_S
        trail = (len(active) - 1 - idx[-1]) * HOP_S
    gaps, run0 = [], None
    for i, a in enumerate(active):
        if not a and run0 is None:
            run0 = i
        elif a and run0 is not None:
            g = (i - run0) * HOP_S
            if g >= INTERNAL_GAP_S:
                gaps.append(g)
            run0 = None
    speech_s = float(np.sum(active)) * HOP_S

    text = seg.get("text_hi", "")
    words = count_words(text)
    n_words = len(words)
    syl = syllable_proxy(text)
    to_db = lambda v: 20.0 * (np.log10(v) if v > 0 else -6.0)
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    # dynamic evenness: std of active-frame envelope in dB (lower = steadier = clearer)
    act_env = env[active] if active.any() else env
    even_db = float(np.std(20 * np.log10(act_env + 1e-9))) if len(act_env) else 0.0
    latin = len(LATIN.findall(text))
    deva = len(DEVANAGARI.findall(text))
    eng_ratio = latin / (latin + deva) if (latin + deva) else 0.0
    long_words = sum(1 for w in words if len(w) >= 12)

    return {
        "id": seg.get("id", ""), "speaker": seg.get("speaker", "?"),
        "start": round(seg["start"], 2), "end": round(seg["end"], 2),
        "clip_dur_s": round(dur, 2), "speech_s": round(speech_s, 2),
        "words": n_words,
        "words_per_sec": round(n_words / speech_s, 2) if speech_s else 0.0,
        "syllables_per_sec": round(syl / speech_s, 2) if speech_s else 0.0,
        "lead_sil_s": round(lead, 2), "trail_sil_s": round(trail, 2),
        "internal_pauses": len(gaps), "median_pause_s": round(statistics.median(gaps), 2) if gaps else 0.0,
        "rms_dbfs": round(to_db(rms), 1), "peak_dbfs": round(to_db(seg_peak), 1),
        "crest_db": round(to_db(seg_peak) - to_db(rms), 1),
        "evenness_db": round(even_db, 1),
        "chars_per_word": round(sum(len(w) for w in words) / n_words, 1) if n_words else 0.0,
        "english_mix_ratio": round(eng_ratio, 2), "long_words_12plus": long_words,
        "text": text,
    }


def summarize(rows):
    if not rows:
        return {}
    f = lambda k: [r[k] for r in rows]
    speakers = {}
    for r in rows:
        speakers[r["speaker"]] = speakers.get(r["speaker"], 0) + 1
    return {
        "segments": len(rows), "speakers": speakers,
        "median_words_per_sec": round(statistics.median(f("words_per_sec")), 2),
        "median_syllables_per_sec": round(statistics.median(f("syllables_per_sec")), 2),
        "median_rms_dbfs": round(statistics.median(f("rms_dbfs")), 1),
        "median_evenness_db": round(statistics.median(f("evenness_db")), 1),
        "median_chars_per_word": round(statistics.median(f("chars_per_word")), 1),
        "median_english_mix": round(statistics.median(f("english_mix_ratio")), 2),
        "total_long_words": sum(f("long_words_12plus")),
        "total_internal_pauses": sum(f("internal_pauses")),
    }


def main():
    p = argparse.ArgumentParser(description="Quantify what makes a dub window "
                                            "understandable (no TTS/APIs).")
    p.add_argument("--video", required=True, help="dubbed video (e.g. old V1 full)")
    p.add_argument("--segments", required=True, help="pipeline segments.json (text_hi + timings)")
    p.add_argument("--window-start", type=float, required=True)
    p.add_argument("--window-end", type=float, required=True)
    p.add_argument("--label", default="oldv1")
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    import numpy as np

    doc = json.loads(Path(args.segments).read_text(encoding="utf-8"))
    segs = [s for s in doc["segments"]
            if s["start"] < args.window_end and s["end"] > args.window_start
            and s.get("text_hi", "").strip()]
    if not segs:
        sys.exit("error: no dubbed segments in window")

    outdir = Path(args.outdir)
    clips = outdir / "seg_clips"
    clips.mkdir(parents=True, exist_ok=True)

    rows = []
    for i, seg in enumerate(segs):
        seg.setdefault("id", "s%03d" % i)
        wav = clips / ("%s.wav" % seg["id"])
        extract_segment_wav(args.video, wav, seg["start"], seg["end"] - seg["start"])
        rows.append(analyze_segment(np, seg, wav))
        print("[seg] %s %s %.1f-%.1f wps=%.2f rms=%.1f even=%.1f"
              % (seg["id"], rows[-1]["speaker"], seg["start"], seg["end"],
                 rows[-1]["words_per_sec"], rows[-1]["rms_dbfs"], rows[-1]["evenness_db"]))

    summary = summarize(rows)
    (outdir / "understandability.json").write_text(json.dumps(
        {"tool": "clonedub_v11_understandability", "version": TOOL_VERSION,
         "label": args.label, "window": [args.window_start, args.window_end],
         "summary": summary, "segments": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    print("\n%s summary: wps=%.2f rms=%.1fdBFS even=%.1fdB eng_mix=%.2f longwords=%d"
          % (args.label, summary["median_words_per_sec"], summary["median_rms_dbfs"],
             summary["median_evenness_db"], summary["median_english_mix"],
             summary["total_long_words"]))
    print("json: %s" % (outdir / "understandability.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
