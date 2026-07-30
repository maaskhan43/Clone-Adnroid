#!/usr/bin/env python3
"""CloneDub V12 Phase 1: scene evidence-pack builder.

Assembles a review pack for ONE scene so a human can understand it before
any generation. Pure assembly/measurement: no TTS, no APIs, no Kaggle,
no LatentSync, no Android. It gathers the source scene clip, the old V1
clip, the failed V11 Phase 6B attempt, the V11 actor-lane/performance
drafts, a contact sheet, and a factual failure analysis.

See CLONEDUB_V12_RASKLIKE_SYSTEM_PLAN.md, Phase 1.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(map(str, cmd)), p.stderr[-1500:]))
    return p.stdout


def sha256(path, limit_mb=None):
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
            read += len(chunk)
            if limit_mb and read >= limit_mb * 1024 * 1024:
                break
    return h.hexdigest()


def stat_entry(path):
    p = Path(path)
    if not p.is_file():
        return {"path": str(p), "exists": False}
    st = p.stat()
    return {"path": str(p), "exists": True, "size_bytes": st.st_size,
            "mtime": int(st.st_mtime), "sha256": sha256(p)}


def ffprobe(path):
    if not Path(path).is_file():
        return {"exists": False}
    try:
        out = run(["ffprobe", "-v", "error", "-show_entries",
                   "format=duration,format_name:stream=index,codec_type,codec_name,"
                   "width,height,r_frame_rate,sample_rate,channels",
                   "-of", "json", str(path)])
    except RuntimeError as e:
        return {"exists": True, "ffprobe_error": str(e)[:300]}
    info = json.loads(out)
    streams = info.get("streams", [])
    return {"exists": True,
            "duration": float(info.get("format", {}).get("duration", 0.0)),
            "format": info.get("format", {}).get("format_name"),
            "video_streams": [s for s in streams if s.get("codec_type") == "video"],
            "audio_streams": [s for s in streams if s.get("codec_type") == "audio"]}


def load_json(path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def dialogue_segments(segments_doc, s, e):
    if not segments_doc:
        return []
    out = []
    for seg in segments_doc.get("segments", []):
        if seg["start"] < e and seg["end"] > s:
            out.append({"start": round(seg["start"], 2), "end": round(seg["end"], 2),
                        "speaker": seg.get("speaker", "?"),
                        "source_text": seg.get("text", "")[:400],
                        "old_v1_text_hi": seg.get("text_hi", "")[:600]})
    return out


def contact_sheet(source_scene, scene_start, media_offset, dur, out_jpg):
    """Frames every ~5s of the scene window into a 4x3 tile."""
    local = scene_start - media_offset
    try:
        run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % local, "-i", str(source_scene),
             "-t", "%.3f" % dur, "-vf", "fps=1/5,scale=320:-1,tile=4x3", str(out_jpg)])
        return Path(out_jpg).is_file()
    except RuntimeError:
        return False


def copy_or_reference(src, dst, do_copy, force):
    src = Path(src)
    entry = stat_entry(src)
    if do_copy and src.is_file():
        if dst.exists() and not force:
            entry["copied"] = False
            entry["copy_note"] = "destination exists; use --force to overwrite"
        else:
            shutil.copy2(src, dst)
            entry["copied"] = True
            entry["local_copy"] = str(dst)
    return entry


def main():
    p = argparse.ArgumentParser(
        description="CloneDub V12 Phase 1: build an evidence pack for one scene "
                    "(assembly only; no TTS/APIs/generation).")
    p.add_argument("--scene-start", type=float, required=True)
    p.add_argument("--scene-end", type=float, required=True)
    p.add_argument("--source-scene", required=True, help="original scene clip")
    p.add_argument("--v1-scene", required=True, help="old V1 scene clip")
    p.add_argument("--segments", required=True, help="pipeline segments.json")
    p.add_argument("--v11-plan-dir", help="V11 Phase 6A performance-plan dir")
    p.add_argument("--v11-gen-dir", help="V11 Phase 6B generation-test dir")
    p.add_argument("--media-offset", type=float, default=1470.0,
                   help="absolute time mapped to the trimmed scene clip's local 0 (default 1470)")
    p.add_argument("--copy-clips", action="store_true",
                   help="copy source/V1/6B clips into the pack (else reference by path+checksum)")
    p.add_argument("--force", action="store_true", help="overwrite existing copied clips")
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    for tool in ("ffprobe", "ffmpeg"):
        if shutil.which(tool) is None:
            sys.exit("error: %s not found on PATH" % tool)

    s, e = args.scene_start, args.scene_end
    dur = round(e - s, 2)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    missing = []

    def note_missing(label, path):
        if not path or not Path(path).is_file():
            missing.append({"label": label, "path": str(path) if path else None})

    # V11 6B failed attempt preview (discover the mp4 in the gen dir)
    v11_gen_preview = None
    if args.v11_gen_dir:
        for cand in Path(args.v11_gen_dir).glob("*.mp4"):
            v11_gen_preview = str(cand)
            break

    # inputs table
    inputs = {
        "source_scene": args.source_scene,
        "v1_scene": args.v1_scene,
        "segments": args.segments,
        "v11_6b_preview": v11_gen_preview,
    }
    for label, path in inputs.items():
        note_missing(label, path)

    # copy or reference the three clips
    clips = {}
    clips["source_scene"] = copy_or_reference(
        args.source_scene, outdir / "clip_source_scene.mp4", args.copy_clips, args.force)
    clips["v1_scene"] = copy_or_reference(
        args.v1_scene, outdir / "clip_v1_scene.mp4", args.copy_clips, args.force)
    if v11_gen_preview:
        clips["v11_6b_attempt"] = copy_or_reference(
            v11_gen_preview, outdir / "clip_v11_6b_attempt.mp4", args.copy_clips, args.force)
    else:
        clips["v11_6b_attempt"] = {"exists": False}

    # ffprobe summaries
    probes = {k: ffprobe(v) for k, v in
              {"source_scene": args.source_scene, "v1_scene": args.v1_scene,
               "v11_6b_preview": v11_gen_preview}.items() if v}

    # dialogue segments
    segments_doc = load_json(args.segments)
    segs = dialogue_segments(segments_doc, s, e)

    # V11 6A drafts -> pack drafts
    plan_dir = Path(args.v11_plan_dir) if args.v11_plan_dir else None
    v11_perf = load_json(plan_dir / "performance_script.json") if plan_dir else None
    v11_lanes = load_json(plan_dir / "actor_lanes.json") if plan_dir else None
    gen_dir = Path(args.v11_gen_dir) if args.v11_gen_dir else None
    v11_gen_report = load_json(gen_dir / "gen_report.json") if gen_dir else None
    for label, obj, path in [
            ("v11_performance_script", v11_perf, plan_dir and plan_dir / "performance_script.json"),
            ("v11_actor_lanes", v11_lanes, plan_dir and plan_dir / "actor_lanes.json"),
            ("v11_6b_gen_report", v11_gen_report, gen_dir and gen_dir / "gen_report.json")]:
        if obj is None:
            missing.append({"label": label, "path": str(path) if path else None})

    # write drafts (copies of V11 6A, marked as drafts to iterate in V12)
    if v11_lanes is not None:
        (outdir / "actor_lanes_draft.json").write_text(
            json.dumps({"source": "V11 Phase 6A actor_lanes.json", "draft": True, **v11_lanes},
                       indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        (outdir / "actor_lanes_draft.json").write_text(
            json.dumps({"draft": True, "lanes": [], "note": "no V11 actor lanes found"},
                       indent=2), encoding="utf-8")
    if v11_perf is not None:
        (outdir / "performance_script_draft.json").write_text(
            json.dumps({"source": "V11 Phase 6A performance_script.json", "draft": True, **v11_perf},
                       indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        (outdir / "performance_script_draft.json").write_text(
            json.dumps({"draft": True, "lines": [], "note": "no V11 performance script found"},
                       indent=2), encoding="utf-8")

    # contact sheet
    sheet_ok = contact_sheet(args.source_scene, s, args.media_offset, dur,
                             outdir / "contact_sheet.jpg")
    if not sheet_ok:
        missing.append({"label": "contact_sheet", "path": str(outdir / "contact_sheet.jpg")})

    # manifest
    manifest = {
        "tool": "v12_scene_pack_builder", "version": TOOL_VERSION,
        "scene": {"start": s, "end": e, "duration": dur, "media_offset": args.media_offset,
                  "local_start": round(s - args.media_offset, 2),
                  "local_end": round(e - args.media_offset, 2)},
        "inputs": {k: stat_entry(v) for k, v in inputs.items() if v},
        "clips_in_pack": clips,
        "ffprobe": probes,
        "dialogue_segments": segs,
        "v11_links": {
            "plan_dir": str(plan_dir) if plan_dir else None,
            "gen_dir": str(gen_dir) if gen_dir else None,
            "performance_script_lines": len(v11_perf.get("lines", [])) if v11_perf else 0,
            "actor_lanes": len(v11_lanes.get("lanes", [])) if v11_lanes else 0,
            "v11_6b_lane_voice": v11_gen_report.get("lane_voice") if v11_gen_report else None,
            "v11_6b_preview": v11_gen_preview,
        },
        "missing_artifacts": missing,
        "contact_sheet": str(outdir / "contact_sheet.jpg") if sheet_ok else None,
    }
    (outdir / "scene_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # failure analysis (factual)
    lanes_txt = ", ".join("%s(%s)" % (l.get("actor_lane_id"), l.get("voice_gender_guess"))
                          for l in (v11_lanes.get("lanes", []) if v11_lanes else [])) or "none"
    fa = [
        "# V12 scene pack - failure analysis (1500.25-1561.13 cake/phone confrontation)", "",
        "Factual summary from artifacts in this pack. No speculation beyond what is recorded.", "",
        "## What V11 attempted (Phase 6A/6B)",
        "- Phase 6A/6A.1: broke the two monolithic old-V1 paragraphs (26s + 27s literal) into "
        "%d short actor beats across %d stable actor lanes: %s." % (
            len(v11_perf.get("lines", [])) if v11_perf else 0,
            len(v11_lanes.get("lanes", [])) if v11_lanes else 0, lanes_txt),
        "- Phase 6B: generated a 60s test with a DISTINCT voice per actor lane "
        "(%s), keyed on actor_lane_id, not the SPEAKER_14 diarization." % (
            ", ".join("%s=%s" % (k, v) for k, v in v11_gen_report["lane_voice"].items())
            if v11_gen_report and v11_gen_report.get("lane_voice") else "lane voices recorded in gen_report"),
        "",
        "## Why the human rejected it",
        "- Human listening gate on the 6B test (and the earlier 900-960 mix-only variants) said the "
        "result still does not feel like a real dubbed movie: characters do not feel like they are "
        "speaking inside the scene.",
        "- Earlier V11 rejections (recorded in the V12 plan section 0): voice/provider bakeoff, "
        "clean-text 3-min previews, and Rask-style mix-only variants were all rejected too.",
        "- Net: the failure reproduced even with short acted lines + distinct per-character voices, "
        "so it is not explained by provider choice or mix level alone.",
        "",
        "## Evidence present in this pack",
        "- source scene clip, old V1 scene clip, and the V11 6B failed attempt "
        "(%s)." % ("copied into pack" if args.copy_clips else "referenced by path+SHA256"),
        "- %d dialogue segments in-window (source ZH + old V1 Hindi)." % len(segs),
        "- V11 actor-lane and performance-script drafts.",
        "- contact sheet (%s)." % ("present" if sheet_ok else "FAILED to render"),
        "",
        "## What is still unknown",
        "- Exact on-screen face<->line attribution (source diarization collapsed all to SPEAKER_14; "
        "3 V11 lanes were flagged needs_human_role_review).",
        "- Whether the break-of-illusion is voice timbre, acting/prosody, line wording, or reaction "
        "timing - the human gate did not isolate a single cause.",
        "- Whether expressive/S2S generation (not covered by Fish/Eleven/Azure TTS) would change the feel.",
        "",
        "## Why Phase 2 focuses on scene understanding / actor lanes first",
        "- Generation has already been tried and rejected; repeating it without better scene/role "
        "understanding would just reproduce the same failure.",
        "- The one concrete, still-unresolved gap is role identity (who is speaking on screen) and "
        "scene-motivated timing - both are scene-understanding problems, not generator settings.",
        "- V12 plan section 4.1/4.2: lock scene understanding + stable actor lanes before spending "
        "more generation.", "",
    ]
    (outdir / "failure_analysis.md").write_text("\n".join(fa), encoding="utf-8")

    # next questions (the 5 human-gate questions, adapted)
    nq = [
        "# V12 human-gate questions - scene 1500.25-1561.13", "",
        "Ask ONLY these for any sample of this scene:", "",
        "1. Does it feel like the characters are arguing inside this scene "
        "(cake dropped -> apology -> confrontation)?",
        "2. Which moment breaks the illusion first (timestamp if possible)?",
        "3. Is the issue voice timbre, acting/emotion, line wording, timing, wrong character voice, or mix?",
        "4. Is it better than the previous baseline (old V1 / the V11 6B attempt)?",
        "5. Should we iterate this scene, or abandon this approach?", "",
        "If you cannot name the difference, that is a valid answer - the system will provide "
        "simpler A/B tests rather than ask for audio vocabulary.", "",
    ]
    (outdir / "next_questions.md").write_text("\n".join(nq), encoding="utf-8")

    # README
    rd = [
        "# V12 scene pack - meteor 1500.25-1561.13 (cake/phone confrontation)", "",
        "Evidence pack built by `v12_scene_pack_builder.py` (Phase 1). No generation - this is "
        "for understanding the scene and its V11 failure before any V12 generation.", "",
        "## Contents",
        "- `scene_manifest.json` - all inputs, checksums, ffprobe, dialogue segments, V11 links, missing list",
        "- `failure_analysis.md` - factual account of what V11 tried and why it was rejected",
        "- `next_questions.md` - the 5 human-gate questions for this scene",
        "- `contact_sheet.jpg` - frames every ~5s of the scene",
        "- `actor_lanes_draft.json` / `performance_script_draft.json` - V11 6A drafts to iterate in V12",
        "- clips: %s" % ("copied into this pack" if args.copy_clips
                          else "referenced by absolute path + SHA256 in the manifest"),
        "",
        "## Scene",
        "- absolute %.2f-%.2f s (%.2fs); local %.2f-%.2f in the source scene clip (offset %.1f)."
        % (s, e, dur, s - args.media_offset, e - args.media_offset, args.media_offset),
        "- %d in-window dialogue segments; %d V11 actor lanes; %d V11 performance-script lines."
        % (len(segs), len(v11_lanes.get("lanes", [])) if v11_lanes else 0,
           len(v11_perf.get("lines", [])) if v11_perf else 0),
        "",
        "## Missing artifacts" if missing else "## Missing artifacts: none",
    ]
    for m in missing:
        rd.append("- %s: %s" % (m["label"], m["path"]))
    rd.append("")
    (outdir / "README.md").write_text("\n".join(rd), encoding="utf-8")

    print("scene pack: %s" % outdir)
    print("  dialogue segments: %d | V11 lanes: %d | V11 script lines: %d"
          % (len(segs), len(v11_lanes.get("lanes", [])) if v11_lanes else 0,
             len(v11_perf.get("lines", [])) if v11_perf else 0))
    print("  contact sheet: %s | missing artifacts: %d" % (sheet_ok, len(missing)))
    for m in missing:
        print("    MISSING: %s -> %s" % (m["label"], m["path"]))
    print("  files: README.md, scene_manifest.json, failure_analysis.md, next_questions.md,")
    print("         contact_sheet.jpg, actor_lanes_draft.json, performance_script_draft.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
