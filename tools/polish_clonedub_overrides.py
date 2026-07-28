#!/usr/bin/env python3
"""Generate Indian spoken Roman-Hindi/Hinglish translation overrides.

This is a one-off production helper for CloneDub artifacts. It reads the
current segments and existing override decisions, preserves editorial
exclusions, and rewrites spoken dialogue into short Indian TV-dub style lines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import requests


DEVANAGARI = re.compile(r"[\u0900-\u097F]")
SOURCE_CJK = re.compile(r"[\u3400-\u9FFF]")


def source_text_checksum(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def groq_keys() -> list[str]:
    return [k for k in [os.environ.get("GROQ_KEY_1", ""), os.environ.get("GROQ_KEY_2", "")] if k]


SYSTEM_PROMPT = """You are a senior Indian TV-dub dialogue writer.

Rules:
- Output exactly one spoken line only. No labels, notes, quotes, bullets, JSON, or alternatives.
- Use Roman script only. Do not use Devanagari. Do not use Chinese.
- Make it sound like normal Indian people talking. No bookish Hindi. No international-English rhythm.
- Translate the Chinese source directly. The rough old line may be wrong, so do not copy its awkward wording.
- Keep character names and story facts, but remove filler, moral lessons, invented explanations, and repeated ideas.
- Keep it duration-friendly for dubbing: short clauses, easy breaths, natural pauses.
- Use Hindi words for numbers when natural: atharah, chaar, teen, do, ek.
- Keep English only when Indians naturally use it: phone, signal, call, internet, game, college, senior, birthday, photo.
- Avoid words like forever, alternative, experience, leadership, objective, philosophy, bottleneck, nutrition department if a simple Hindi word works.
- For poetic/song-like source, make a short emotional spoken/poetic Hindi line; do not explain the poem.
- For narration, use clean spoken Hindi/Hinglish. For arguments, make it punchy and natural.
"""


def clean_line(text: str) -> str:
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()
    text = re.sub(r"^(Hindi|Hinglish|Line|Output)\s*:\s*", "", text, flags=re.I).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def polish_one(source: str, old: str, target_dur: float, keys: list[str], model: str, idx: int) -> str:
    user = (
        f"Target spoken duration: about {target_dur:.1f} seconds.\n"
        f"Segment index: {idx}\n"
        f"Chinese source:\n{source}\n\n"
        "Write the final Indian spoken Roman-Hindi/Hinglish dub line from the Chinese source. "
        "Do not copy any previous machine-translation wording."
    )
    last = None
    for attempt in range(6):
        key = keys[attempt % len(keys)]
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "temperature": 0.18,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=60,
            )
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            out = clean_line(r.json()["choices"][0]["message"]["content"])
            if out and not DEVANAGARI.search(out) and not SOURCE_CJK.search(out):
                return normalize_indian_roman(out)
            last = f"bad script/empty output: {out[:80]!r}"
            user += "\n\nPrevious output used wrong script or was empty. Roman Hinglish only."
            continue
        if r.status_code in (401, 403, 429, 500, 502, 503, 504):
            last = f"retryable status {r.status_code}: {r.text[:120]}"
            retry_after = r.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after else 2 * (attempt + 1))
            continue
        raise RuntimeError(f"Groq fatal for segment {idx}: {r.status_code} {r.text[:200]}")
    raise RuntimeError(f"Groq polish failed for segment {idx}: {last}")


def normalize_indian_roman(line: str) -> str:
    """Small deterministic cleanup for common model phrasing slips."""
    replacements = {
        "Mere naam": "Mera naam",
        "mere naam": "mera naam",
        "bhavishya": "aage",
        "Bhavishya": "Aage",
        "jeevan": "zindagi",
        "Jeevan": "Zindagi",
        "eighteen": "atharah",
        "Eighteen": "Atharah",
        "forever": "hamesha",
        "Forever": "Hamesha",
        "alternative": "jawab",
        "Alternative": "Jawab",
    }
    for old, new in replacements.items():
        line = line.replace(old, new)
    return clean_line(line)


def refine_line(line: str, source: str, target_dur: float, keys: list[str], model: str, idx: int) -> str:
    """Second-pass copy edit for Indian spoken grammar and accent cues."""
    system = """You are an Indian Hindi dub dialogue editor.
Output one final Roman-Hindi/Hinglish spoken line only.
Fix grammar, awkward phrasing, bookish words, and English rhythm.
Do not add new plot information. Do not remove important meaning.
No Devanagari. No Chinese. No notes."""
    user = (
        f"Target duration: about {target_dur:.1f}s.\n"
        f"Chinese source for meaning check: {source}\n"
        f"Draft Roman-Hindi line: {line}\n\n"
        "Make it sound like a natural Indian serial/movie dub. "
        "Prefer: zindagi over jeevan, aage over bhavishya, Mera naam over Mere naam, "
        "atharah saal over eighteen years. Keep it concise."
    )
    last = None
    for attempt in range(4):
        key = keys[(idx + attempt) % len(keys)]
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "temperature": 0.12,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=60,
            )
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            out = clean_line(r.json()["choices"][0]["message"]["content"])
            if out and not DEVANAGARI.search(out) and not SOURCE_CJK.search(out):
                return out
            last = f"bad script/empty refined output: {out[:80]!r}"
            continue
        if r.status_code in (401, 403, 429, 500, 502, 503, 504):
            last = f"retryable status {r.status_code}: {r.text[:120]}"
            retry_after = r.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after else 2 * (attempt + 1))
            continue
        raise RuntimeError(f"Groq refine fatal for segment {idx}: {r.status_code} {r.text[:200]}")
    raise RuntimeError(f"Groq refine failed for segment {idx}: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--model", default=os.environ.get("GROQ_REWRITE_MODEL", "llama-3.3-70b-versatile"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    work = Path(args.workdir)
    seg_path = work / "segments.json"
    override_path = work / "translation_overrides.json"
    progress_path = work / "translation_overrides.polish_progress.json"
    out_path = work / "translation_overrides.polished.json"

    keys = groq_keys()
    if not keys:
        raise RuntimeError("GROQ_KEY_1/2 missing")

    data = json.loads(seg_path.read_text(encoding="utf-8"))
    segments = data["segments"]
    old_payload = json.loads(override_path.read_text(encoding="utf-8")) if override_path.exists() else {"segments": {}}
    old_entries = old_payload.get("segments", {})
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}

    new_entries: dict[str, dict] = {}
    done = 0
    for i, s in enumerate(segments):
        src = (s.get("text") or "").strip()
        source_checksum = source_text_checksum(src)
        old_item = old_entries.get(str(i), {})
        # Preserve reviewed/editorial exclusions and placement evidence exactly.
        if old_item and not (s.get("text_hi") or "").strip():
            new_entries[str(i)] = dict(old_item)
            continue
        if not src:
            new_entries[str(i)] = {"source_checksum": source_checksum, "text_hi": ""}
            continue
        old_text = (s.get("text_hi") or old_item.get("text_hi") or "").strip()
        cache = progress.get(str(i))
        if cache and cache.get("source_checksum") == source_checksum and cache.get("old_text") == old_text:
            polished = cache["text_hi"]
        else:
            target_dur = max(float(s.get("end", 0)) - float(s.get("start", 0)), 0.2)
            polished = polish_one(src, old_text, target_dur, keys, args.model, i)
            progress[str(i)] = {
                "source_checksum": source_checksum,
                "old_text": old_text,
                "text_hi": polished,
                "model": args.model,
            }
            progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            done += 1
            print(f"[{i}] {polished}", flush=True)
            if args.limit and done >= args.limit:
                break
        new_entries[str(i)] = {"source_checksum": source_checksum, "text_hi": polished}

    if args.limit and done >= args.limit:
        print(f"LIMIT_REACHED generated={done}; progress saved at {progress_path}")
        return 0

    # Add any preserved entries not encountered due unusual index layout.
    for k, v in old_entries.items():
        new_entries.setdefault(k, v)
    payload = {
        "style": "indian_spoken_roman_hinglish_v1",
        "model": args.model,
        "segments": dict(sorted(new_entries.items(), key=lambda kv: int(kv[0]))),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    override_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {override_path} segments={len(new_entries)} generated_or_reused={len(progress)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
